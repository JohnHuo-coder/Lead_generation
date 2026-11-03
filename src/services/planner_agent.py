from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command
from langgraph_sdk import get_client
from pydantic import BaseModel, Field

from components.state import PlannerAgentState
from llm.models import llm
from prompts.planner import PLANNER_SYSTEM_PROMPT
from prompts.rules import format_skill_catalog, resolve_skill_ids
from schemas.research_schemas import ResearchPlan
from services.user_store import (
    aget_profile,
    aget_run,
    aput_profile,
    aput_run,
    aupdate_run_status,
    current_store,
    get_profile,
    get_user_id,
    put_profile,
)

logger = logging.getLogger(__name__)

# Graph name from langgraph.json; override if the deployed assistant id differs.
ORCHESTRATOR_ASSISTANT_ID = os.getenv("ORCHESTRATOR_ASSISTANT_ID", "orchestrator")

# Plan-lock replies that must not be treated as scrape answers.
_CONFIRM_ONLY_RE = re.compile(
    r"^\s*(confirm|confirmed|looks good|lgtm|ok|okay|yes|yep|yeah|sure|"
    r"go ahead|approved)\s*[.!]?\s*$",
    re.IGNORECASE,
)


def _langgraph_api_url() -> str | None:
    """Optional remote URL override; ``None`` means in-process Agent Server.

    Inside ``langgraph dev`` / ``up`` / LangSmith deploy, prefer ``url=None`` so
    ``get_client`` uses the ASGI loopback and no public deployment URL is
    required before deploy. Set ``LANGGRAPH_API_URL`` (or
    ``LANGGRAPH_DEPLOYMENT_URL``) only to call a *different* remote server.
    """
    return (
        os.getenv("LANGGRAPH_API_URL")
        or os.getenv("LANGGRAPH_DEPLOYMENT_URL")
        or None
    )


def _message_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("type") or msg.get("role") or "").lower()
    return str(getattr(msg, "type", None) or getattr(msg, "role", "") or "").lower()


def _message_text(msg: Any) -> str:
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(getattr(block, "text", "") or ""))
        return "\n".join(parts)
    return str(content or "")


def _last_human_text(messages: Any) -> str:
    for msg in reversed(messages or []):
        if _message_role(msg) in {"human", "user"}:
            return _message_text(msg).strip()
    return ""


def _user_stated_scrape_number(text: str, number: int) -> bool:
    """True only when the latest user message explicitly includes this count."""
    if not text or _CONFIRM_ONLY_RE.match(text):
        return False
    return bool(re.search(rf"(?<!\d){int(number)}(?!\d)", text))


class ScrapeTarget(BaseModel):
    location: str = Field(description="City or area to search, e.g. Bangkok Sukhumvit.")
    company_type: str = Field(
        description="Google Maps search string, e.g. hotel or boutique hotel."
    )
    number: int = Field(
        ge=1,
        le=100,
        description=(
            "How many places to scrape (1-100). Must be a number the user "
            "explicitly stated in their latest message — never invent or default."
        ),
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
    questions. Do not call set_scrape_target in the same turn — wait for
    the user's next message with location, company type, and number.
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
                        "Research plan locked and saved. Do NOT call "
                        "set_scrape_target yet. Reply to the user asking for "
                        "scrape location, company type, and an explicit number "
                        "of places (1-100). Call set_scrape_target only after "
                        "their next message states all three — never invent them."
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

    Call only after the user has stated location, company type, and number in
    a message after plan confirmation. Never invent or default the number.
    Do not call this in the same turn as submit_research_plan when the user
    only said confirm.
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

    last_human = _last_human_text(runtime.state.get("messages"))
    if not _user_stated_scrape_number(last_human, target.number):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "Rejected: the user's latest message does not "
                            f"explicitly state number={target.number}. Ask for "
                            "location, company type, and how many places "
                            "(1-100) as a digit, then call again only after "
                            "they answer. Do not invent scrape parameters."
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


async def _enqueue_orchestrator_run(*, user_id: str, run_id: str) -> dict[str, Any]:
    """Create a platform thread + background orchestrator run (in-process by default)."""
    client = get_client(url=_langgraph_api_url())
    thread = await client.threads.create(
        metadata={
            "user_id": user_id,
            "research_run_id": run_id,
            "graph": ORCHESTRATOR_ASSISTANT_ID,
        },
    )
    thread_id = thread["thread_id"]
    run = await client.runs.create(
        thread_id,
        ORCHESTRATOR_ASSISTANT_ID,
        input={"user_id": user_id, "run_id": run_id},
        config={
            "configurable": {
                "user_id": user_id,
                "run_id": run_id,
            }
        },
        metadata={
            "user_id": user_id,
            "research_run_id": run_id,
        },
    )
    return {
        "lg_thread_id": thread_id,
        "lg_run_id": run.get("run_id"),
    }


async def _launch_orchestrator(
    *, user_id: str, run_id: str, store
) -> dict[str, Any]:
    """Enqueue orchestrator as a LangGraph Platform background run.

    Uses ``get_client(url=None)`` (in-process) unless a remote URL is set.
    Returns platform thread/run ids. On API failure, marks the research run
    as error and re-raises.
    """
    try:
        platform = await _enqueue_orchestrator_run(user_id=user_id, run_id=run_id)
    except Exception as exc:
        logger.exception(
            "Failed to enqueue orchestrator run %s via LangGraph API", run_id
        )
        await aupdate_run_status(
            store,
            run_id,
            "error",
            error=(
                "Failed to start orchestrator via LangGraph API: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
        raise

    await aput_run(
        store,
        run_id,
        {
            "lg_thread_id": platform["lg_thread_id"],
            "lg_run_id": platform["lg_run_id"],
            "lg_assistant_id": ORCHESTRATOR_ASSISTANT_ID,
        },
    )
    logger.info(
        "Enqueued orchestrator research_run_id=%s lg_thread_id=%s lg_run_id=%s",
        run_id,
        platform["lg_thread_id"],
        platform["lg_run_id"],
    )
    return platform


@tool
async def start_research_run(
    runtime: ToolRuntime[None, PlannerAgentState],
) -> Command:
    """Start the background scrape + research batch for the locked plan.

    Requires a locked research_plan and scrape_target. Enqueues the
    orchestrator graph via the LangGraph API and returns immediately;
    the user can keep chatting. Use get_research_status to check progress.
    """
    user_id = get_user_id(runtime.config)
    store = current_store(runtime.store)
    profile = await aget_profile(store, user_id)

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
    await aput_run(
        store,
        run_id,
        {
            "run_id": run_id,
            "user_id": user_id,
            "status": "queued",
            "created_at": now,
            # Snapshot plan/target on the run in case the profile changes later.
            "research_plan": plan,
            "scrape_target": scrape_target,
            "companies": [],
            "pair_results": [],
            "results_by_company": {},
            "error": "",
        },
    )
    await aput_profile(store, user_id, {"active_run_id": run_id})

    try:
        platform = await _launch_orchestrator(
            user_id=user_id, run_id=run_id, store=store
        )
    except Exception as exc:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"Failed to enqueue research run {run_id} on the "
                            f"LangGraph API: {type(exc).__name__}: {exc}. "
                            "In-process enqueue needs to run inside "
                            "langgraph dev / up / deploy; set "
                            "LANGGRAPH_API_URL only to target a remote server."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        f"Research run queued (run_id={run_id}, "
                        f"lg_run_id={platform.get('lg_run_id')}). "
                        "You can keep chatting. Call get_research_status for progress."
                    ),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


@tool
async def get_research_status(
    runtime: ToolRuntime[None, PlannerAgentState],
) -> Command:
    """Return status of the user's active (or latest) research run."""
    user_id = get_user_id(runtime.config)
    store = current_store(runtime.store)
    profile = await aget_profile(store, user_id)
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

    run = await aget_run(store, run_id)
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
    if run.get("lg_run_id"):
        lines.append(f"lg_run_id: {run.get('lg_run_id')}")
    if run.get("lg_thread_id"):
        lines.append(f"lg_thread_id: {run.get('lg_thread_id')}")
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


def planner_graph():
    """LangGraph graph factory (langgraph.json: planner).

    Lazy-builds the agent so import does not require a live DB until first use.
    Must be a zero-arg (or ServerRuntime/RunnableConfig) factory — a callable
    proxy object is rejected by langgraph-api.
    """
    return get_planner_agent()

