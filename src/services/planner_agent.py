from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone

from langchain.agents import create_agent
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command
from pydantic import BaseModel, Field

from components.state import PlannerAgentState
from llm.models import llm
from prompts.planner import PLANNER_SYSTEM_PROMPT
from prompts.rules import format_skill_catalog, resolve_skill_ids
from schemas.research_schemas import ResearchPlan
from services.user_store import (
    bind_thread_store,
    clear_thread_store,
    current_store,
    get_planner_checkpointer,
    get_planner_store,
    get_profile,
    get_run,
    get_user_id,
    put_profile,
    put_run,
    update_run_status,
)

logger = logging.getLogger(__name__)


class ScrapeTarget(BaseModel):
    location: str = Field(description="City or area to search, e.g. Bangkok Sukhumvit.")
    company_type: str = Field(
        description="Google Maps search string, e.g. hotel or boutique hotel."
    )
    number: int = Field(
        ge=1,
        le=100,
        description="How many places to scrape (1-100).",
    )


@tool
def submit_research_plan(
    plan: ResearchPlan,
    runtime: ToolRuntime[None, PlannerAgentState],
) -> Command:
    """Lock the confirmed research plan after the user approves it.

    Call only after you have shown every requirement's description,
    positive_when, negative_when, does_not_count, and skills, and the
    user has explicitly confirmed. Do not call this to draft or to ask
    questions.
    """
    if not plan.requirements:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Rejected: a plan needs at least one requirement.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    plan = plan.model_copy(
        update={
            "requirements": [
                requirement.model_copy(
                    update={"skills": resolve_skill_ids(requirement.skills)}
                )
                for requirement in plan.requirements
            ]
        }
    )

    user_id = get_user_id(runtime.config)
    store = current_store(runtime.store)
    put_profile(
        store,
        user_id,
        {
            "research_plan": plan.model_dump(),
            "scrape_target": None,
            "active_run_id": None,
        },
    )

    return Command(
        update={
            "research_plan": plan,
            "messages": [
                ToolMessage(
                    content=(
                        "Research plan locked and saved. Next ask for scrape "
                        "location, company type, and how many places to collect, "
                        "then call set_scrape_target."
                    ),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


@tool
def set_scrape_target(
    target: ScrapeTarget,
    runtime: ToolRuntime[None, PlannerAgentState],
) -> Command:
    """Save Google Maps scrape parameters after the research plan is locked.

    Call only when research_plan is already locked and the user has provided
    location, company type, and number.
    """
    user_id = get_user_id(runtime.config)
    store = current_store(runtime.store)
    profile = get_profile(store, user_id)
    if not profile.get("research_plan") and not runtime.state.get("research_plan"):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Rejected: lock a research plan with "
                            "submit_research_plan first."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    scrape_target = target.model_dump()
    put_profile(store, user_id, {"scrape_target": scrape_target})
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        "Scrape target saved: "
                        f"location={target.location!r}, "
                        f"company_type={target.company_type!r}, "
                        f"number={target.number}. "
                        "When the user wants to begin, call start_research_run."
                    ),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


def _launch_orchestrator(*, user_id: str, run_id: str, store) -> None:
    def _run() -> None:
        bind_thread_store(store)
        try:
            from graphs.orchestrator_graph import orchestrator_graph

            orchestrator_graph.invoke(
                {"user_id": user_id, "run_id": run_id},
                config={
                    "configurable": {
                        "user_id": user_id,
                        "run_id": run_id,
                    }
                },
            )
        except Exception as exc:
            logger.exception("Orchestrator run %s failed", run_id)
            update_run_status(
                store,
                run_id,
                "error",
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            clear_thread_store()

    thread = threading.Thread(
        target=_run,
        name=f"orchestrator-{run_id}",
        daemon=True,
    )
    thread.start()


@tool
def start_research_run(
    runtime: ToolRuntime[None, PlannerAgentState],
) -> Command:
    """Start the background scrape + research batch for the locked plan.

    Requires a locked research_plan and scrape_target. Returns immediately;
    the user can keep chatting. Use get_research_status to check progress.
    """
    user_id = get_user_id(runtime.config)
    store = current_store(runtime.store)
    profile = get_profile(store, user_id)

    plan = profile.get("research_plan")
    if not plan and runtime.state.get("research_plan") is not None:
        plan_obj = runtime.state["research_plan"]
        plan = (
            plan_obj.model_dump()
            if hasattr(plan_obj, "model_dump")
            else plan_obj
        )
    scrape_target = profile.get("scrape_target")
    if not plan:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Rejected: lock a research plan with "
                            "submit_research_plan first."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )
    if not scrape_target:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Rejected: set scrape location/type/number with "
                            "set_scrape_target first."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    put_run(
        store,
        run_id,
        {
            "run_id": run_id,
            "user_id": user_id,
            "status": "queued",
            "created_at": now,
            "research_plan": plan,
            "scrape_target": scrape_target,
            "companies": [],
            "pair_results": [],
            "results_by_company": {},
            "error": "",
        },
    )
    put_profile(store, user_id, {"active_run_id": run_id})
    _launch_orchestrator(user_id=user_id, run_id=run_id, store=store)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        f"Research run started in the background (run_id={run_id}). "
                        "You can keep chatting. Call get_research_status for progress."
                    ),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


@tool
def get_research_status(
    runtime: ToolRuntime[None, PlannerAgentState],
) -> Command:
    """Return status of the user's active (or latest) research run."""
    user_id = get_user_id(runtime.config)
    store = current_store(runtime.store)
    profile = get_profile(store, user_id)
    run_id = profile.get("active_run_id")
    if not run_id:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="No research run has been started yet.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    run = get_run(store, run_id)
    if not run:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Run {run_id} was not found in the store.",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    status = run.get("status") or "unknown"
    lines = [
        f"run_id: {run_id}",
        f"status: {status}",
    ]
    if run.get("company_count") is not None:
        lines.append(f"companies_scraped: {run.get('company_count')}")
    if run.get("pair_total") is not None:
        lines.append(
            f"pairs_done: {run.get('pair_done', 0)} / {run.get('pair_total')}"
        )
    if run.get("pairs_error") is not None:
        lines.append(f"pairs_error: {run.get('pairs_error')}")
    if run.get("companies_total") is not None:
        lines.append(f"companies_total: {run.get('companies_total')}")
        lines.append(f"companies_passed: {run.get('companies_passed', 0)}")
        lines.append(f"companies_failed: {run.get('companies_failed', 0)}")
    if status == "done":
        saved = run.get("results_saved")
        table = run.get("results_table") or "research_run_results"
        if saved is not None:
            lines.append(
                f"results_saved: {saved} rows in {table} "
                "(open the results page to browse companies)"
            )
        else:
            lines.append(
                f"results stored in {table} "
                "(open the results page to browse companies)"
            )
    if run.get("error"):
        lines.append(f"error: {run['error']}")

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content="\n".join(lines),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


def _build_planner_graph():
    return create_agent(
        model=llm,
        tools=[
            submit_research_plan,
            set_scrape_target,
            start_research_run,
            get_research_status,
        ],
        state_schema=PlannerAgentState,
        system_prompt=PLANNER_SYSTEM_PROMPT.format(
            skill_catalog=format_skill_catalog(),
        ),
        checkpointer=get_planner_checkpointer(),
        store=get_planner_store(),
    )


_planner_graph = None
_planner_graph_lock = threading.Lock()


def get_planner_agent():
    global _planner_graph
    if _planner_graph is None:
        with _planner_graph_lock:
            if _planner_graph is None:
                _planner_graph = _build_planner_graph()
    return _planner_graph


# langgraph.json loads this symbol; defer DB connect until first use via proxy.
class _PlannerGraphProxy:
    def __getattr__(self, name: str):
        return getattr(get_planner_agent(), name)

    def __call__(self, *args, **kwargs):
        return get_planner_agent()(*args, **kwargs)


planner_graph = _PlannerGraphProxy()
