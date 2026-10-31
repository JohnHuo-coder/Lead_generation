from __future__ import annotations

import logging
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from components.constants import MAX_RESEARCH_CONCURRENCY
from graphs.main_graph import research_subgraph
from schemas.research_schemas import ResearchPlan
from services.gmap_scrape import scrape_companies
from services.user_store import (
    current_store,
    get_profile,
    get_run,
    put_run,
    update_run_status,
)

logger = logging.getLogger(__name__)


class OrchestratorState(TypedDict):
    user_id: str
    run_id: str
    research_plan: NotRequired[dict[str, Any]]
    scrape_target: NotRequired[dict[str, Any]]
    companies: NotRequired[list[dict[str, Any]]]
    # Transient only: used to persist rows then discarded from Store summary.
    pair_results: NotRequired[list[dict[str, Any]]]
    companies_total: NotRequired[int]
    companies_passed: NotRequired[int]
    companies_failed: NotRequired[int]
    pairs_total: NotRequired[int]
    pairs_error: NotRequired[int]
    results_saved: NotRequired[int]
    status: NotRequired[str]
    error: NotRequired[str]



def load_run_context(state: OrchestratorState) -> dict[str, Any]:
    user_id = state["user_id"]
    run_id = state["run_id"]
    store = current_store()
    profile = get_profile(store, user_id)
    run = get_run(store, run_id)

    research_plan = run.get("research_plan") or profile.get("research_plan")
    scrape_target = run.get("scrape_target") or profile.get("scrape_target") # {location, company_type, number}
    if not research_plan:
        update_run_status(store, run_id, "error", error="Missing research_plan")
        return {"status": "error", "error": "Missing research_plan"}
    if not scrape_target:
        update_run_status(store, run_id, "error", error="Missing scrape_target")
        return {"status": "error", "error": "Missing scrape_target"}

    update_run_status(store, run_id, "loaded")
    return {
        "research_plan": research_plan,
        "scrape_target": scrape_target,
        "status": "loaded",
        "error": "",
    }


def scrape_companies_node(state: OrchestratorState) -> dict[str, Any]:
    run_id = state["run_id"]
    store = current_store()
    if state.get("status") == "error":
        return {}

    target = state.get("scrape_target") or {}
    location = (target.get("location") or "").strip()
    company_type = (target.get("company_type") or "").strip()
    number = int(target.get("number") or 0)
    if not location or not company_type or number <= 0:
        message = "Invalid scrape_target: need location, company_type, and positive number"
        update_run_status(store, run_id, "error", error=message)
        return {"status": "error", "error": message}

    update_run_status(store, run_id, "scraping")
    try:
        companies = scrape_companies(
            location=location,
            company_type=company_type,
            number=number,
        )
    except Exception as exc:
        logger.exception("Google Maps scrape failed for run %s", run_id)
        message = f"Scrape failed: {exc}"
        update_run_status(store, run_id, "error", error=message)
        return {"status": "error", "error": message, "companies": []}

    put_run(
        store,
        run_id,
        {
            "status": "scraped",
            "companies": companies,
            "company_count": len(companies),
        },
    )
    return {"companies": companies, "status": "scraped", "error": ""}


def _build_research_inputs(
    companies: list[dict[str, Any]],
    plan: ResearchPlan,
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for company in companies:
        name = company.get("company") or ""
        if not name:
            continue
        for requirement in plan.requirements:
            inputs.append(
                {
                    "company": name,
                    "place_id": company.get("place_id") or "",
                    "website": company.get("website"),
                    "requirement_id": requirement.id,
                    "requirement": requirement.description,
                    "positive_when": requirement.positive_when,
                    "negative_when": requirement.negative_when,
                    "does_not_count": list(requirement.does_not_count or []),
                    "skills": list(requirement.skills or []),
                }
            )
    return inputs


def research_batch_node(state: OrchestratorState) -> dict[str, Any]:
    run_id = state["run_id"]
    store = current_store()
    if state.get("status") == "error":
        return {}

    companies = state.get("companies") or []
    plan_data = state.get("research_plan") or {}
    try:
        plan = ResearchPlan.model_validate(plan_data)
    except Exception as exc:
        message = f"Invalid research_plan: {exc}"
        update_run_status(store, run_id, "error", error=message)
        return {"status": "error", "error": message}

    inputs = _build_research_inputs(companies, plan)
    total = len(inputs)
    update_run_status(
        store,
        run_id,
        "researching",
        pair_total=total,
        pair_done=0,
    )
    if total == 0:
        put_run(
            store,
            run_id,
            {
                "status": "done",
                "pair_results": [],
                "results_by_company": {},
                "pair_total": 0,
                "pair_done": 0,
            },
        )
        return {
            "pair_results": [],
            "results_by_company": {},
            "status": "done",
        }

    # Drop non-ResearchInput keys before invoke; keep them for aggregation.
    research_inputs = [
        {
            "company": item["company"],
            "requirement": item["requirement"],
            "positive_when": item["positive_when"],
            "negative_when": item["negative_when"],
            "does_not_count": item["does_not_count"],
            "skills": item["skills"],
        }
        for item in inputs
    ]

    raw_results = research_subgraph.batch(
        research_inputs,
        config={"max_concurrency": MAX_RESEARCH_CONCURRENCY},
        return_exceptions=True,
    )

    pair_results: list[dict[str, Any]] = []
    for meta, result in zip(inputs, raw_results, strict=True):
        if isinstance(result, Exception):
            pair_results.append(
                {
                    "company": meta["company"],
                    "place_id": meta["place_id"],
                    "requirement_id": meta["requirement_id"],
                    "error": f"{type(result).__name__}: {result}",
                    "sufficient": None,
                    "satisfied": None,
                    "verified_claims": [],
                    "sufficient_reason": "",
                }
            )
            continue
        pair_results.append(
            {
                "company": meta["company"],
                "place_id": meta["place_id"],
                "requirement_id": meta["requirement_id"],
                "sufficient": result.get("sufficient"),
                "satisfied": result.get("satisfied"),
                "verified_claims": list(result.get("verified_claims") or []),
                "sufficient_reason": result.get("sufficient_reason") or "",
                "error": None,
            }
        )

    update_run_status(
        store,
        run_id,
        "researching",
        pair_total=total,
        pair_done=len(pair_results),
    )
    return {"pair_results": pair_results, "status": "researched"}


def aggregate_node(state: OrchestratorState) -> dict[str, Any]:
    run_id = state["run_id"]
    user_id = state["user_id"]
    store = current_store()
    if state.get("status") == "error":
        return {}

    pair_results = state.get("pair_results") or []
    by_company: dict[str, dict[str, Any]] = {}
    pairs_error = 0
    for item in pair_results:
        if item.get("error"):
            pairs_error += 1
        company = item.get("company") or ""
        bucket = by_company.setdefault(
            company,
            {"all_satisfied": True, "any_error": False},
        )
        if item.get("error"):
            bucket["any_error"] = True
            bucket["all_satisfied"] = False
        elif item.get("satisfied") is not True:
            bucket["all_satisfied"] = False

    companies_total = len(by_company)
    companies_passed = sum(
        1 for row in by_company.values() if row.get("all_satisfied")
    )
    companies_failed = companies_total - companies_passed
    pairs_total = len(pair_results)

    results_saved = 0
    try:
        from repositories.research_results_repository import (
            upsert_research_pair_results,
        )

        results_saved = upsert_research_pair_results(
            run_id=run_id,
            user_id=user_id,
            pair_results=pair_results,
        )
    except Exception as exc:
        logger.exception("Persisting research results failed for run %s", run_id)
        message = f"Results DB write failed: {exc}"
        update_run_status(store, run_id, "error", error=message)
        return {"status": "error", "error": message}

    # Store only summary stats for chat/status — full rows live in Postgres.
    put_run(
        store,
        run_id,
        {
            "status": "done",
            "pair_total": pairs_total,
            "pair_done": pairs_total,
            "pairs_error": pairs_error,
            "companies_total": companies_total,
            "companies_passed": companies_passed,
            "companies_failed": companies_failed,
            "results_saved": results_saved,
            "results_table": "research_run_results",
            "pair_results": None,
            "results_by_company": None,
        },
    )
    return {
        "companies_total": companies_total,
        "companies_passed": companies_passed,
        "companies_failed": companies_failed,
        "pairs_total": pairs_total,
        "pairs_error": pairs_error,
        "results_saved": results_saved,
        "pair_results": [],
        "status": "done",
        "error": "",
    }


def _route_after_load(state: OrchestratorState) -> str:
    if state.get("status") == "error":
        return "END"
    return "scrape"


def _route_after_scrape(state: OrchestratorState) -> str:
    if state.get("status") == "error":
        return "END"
    return "research"


orchestrator_builder = StateGraph(OrchestratorState)
orchestrator_builder.add_node("load_context", load_run_context)
orchestrator_builder.add_node("scrape", scrape_companies_node)
orchestrator_builder.add_node("research", research_batch_node)
orchestrator_builder.add_node("aggregate", aggregate_node)

orchestrator_builder.add_edge(START, "load_context")
orchestrator_builder.add_conditional_edges(
    "load_context",
    _route_after_load,
    {"scrape": "scrape", "END": END},
)
orchestrator_builder.add_conditional_edges(
    "scrape",
    _route_after_scrape,
    {"research": "research", "END": END},
)
orchestrator_builder.add_edge("research", "aggregate")
orchestrator_builder.add_edge("aggregate", END)

orchestrator_graph = orchestrator_builder.compile()


def get_orchestrator_graph():
    return orchestrator_graph
