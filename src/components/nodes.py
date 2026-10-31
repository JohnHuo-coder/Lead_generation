import random
from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents.middleware import (
    wrap_model_call,
    ModelRequest,
    ModelResponse,
)

from components.state import (
    OverallState,
    ResearchState,
    FitScoreInput,
    FitScoreUpdate,
    ResearchAgentState,
    RFPInput,
    RFPUpdate,
)
from schemas.research_schemas import ResearchResult
from schemas.fit_scoring_schemas import FitScoreResult
from components.constants import MAX_SEARCH_CALLS
from components.tools import research_search
from prompts.fit_scoring import FIT_SCORING_SYSTEM_PROMPT
from prompts.research import (
    RESEARCH_AGENT_SYSTEM_PROMPT,
    RESEARCH_FINAL_HUMAN_REMINDER,
    RESEARCH_FINAL_SYSTEM_PROMPT,
)
from prompts.rules import resolve_skill_ids, with_domain_rules
from services.skill_selector import choose_domain_skills
from llm.models import (
    llm,
    structured_fit_score_llm,
)
from schemas.rfp_schemas import RfpResult
from services.rfp_agent import get_rfp_agent


_RESEARCH_AGENT_SYSTEM = RESEARCH_AGENT_SYSTEM_PROMPT.replace(
    "{max_search_calls}", str(MAX_SEARCH_CALLS)
)


def _research_system_prompt(base: str, state: dict) -> str:
    return with_domain_rules(base, state.get("skills") or [], "researcher")


def _resolve_research_skills(state: ResearchState) -> list[str]:
    skills = resolve_skill_ids(state.get("skills") or [])
    if skills:
        return skills
    return choose_domain_skills(
        requirement=state.get("requirement") or "",
        positive_when=state.get("positive_when") or "",
        negative_when=state.get("negative_when") or "",
        does_not_count=state.get("does_not_count") or [],
    )


@wrap_model_call
def control_research_search(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:

    model_settings = {
        **(request.model_settings or {}),
        "parallel_tool_calls": False,
    }

    tool_call_count = request.state.get("tool_call_count", 0)

    if tool_call_count < MAX_SEARCH_CALLS:
        return handler(
            request.override(
                system_message=SystemMessage(
                    content=_research_system_prompt(
                        _RESEARCH_AGENT_SYSTEM, request.state
                    )
                ),
                model_settings=model_settings,
            )
        )

    remaining_tools = [
        tool
        for tool in request.tools
        if tool.name != "research_search"
    ]

    final_messages = [
        *request.messages,
        HumanMessage(content=RESEARCH_FINAL_HUMAN_REMINDER),
    ]

    return handler(
        request.override(
            tools=remaining_tools,
            system_message=SystemMessage(
                content=_research_system_prompt(
                    RESEARCH_FINAL_SYSTEM_PROMPT, request.state
                )
            ),
            messages=final_messages,
            tool_choice="ResearchResult",
            model_settings=model_settings,
        )
    )


research_agent = create_agent(
    model=llm,
    tools=[research_search],
    middleware=[control_research_search],
    response_format=ToolStrategy(ResearchResult),
    state_schema=ResearchAgentState,
    system_prompt=_RESEARCH_AGENT_SYSTEM,
)


def _format_does_not_count(items: list[str] | None) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def _evidence_claims(items: list | None) -> list[str]:
    claims: list[str] = []
    for item in items or []:
        claim = item.claim if hasattr(item, "claim") else item.get("claim")
        if claim:
            claims.append(claim)
    return claims


def _judgment_flag(item, field: str) -> bool:
    value = item.get(field) if isinstance(item, dict) else getattr(item, field, False)
    return bool(value)


def _sample_verifier_judgments(judgments: list | None) -> dict:
    """Pick one random example per rejection/accept bucket for eval spot-checks."""
    items = list(judgments or [])
    supported = [item for item in items if _judgment_flag(item, "support")]
    wrong_company = [
        item for item in items if not _judgment_flag(item, "about_this_company")
    ]
    unsupported = [
        item
        for item in items
        if _judgment_flag(item, "about_this_company")
        and not _judgment_flag(item, "support")
    ]
    return {
        "verifier_sample_supported": (
            random.choice(supported) if supported else None
        ),
        "verifier_sample_wrong_company": (
            random.choice(wrong_company) if wrong_company else None
        ),
        "verifier_sample_unsupported": (
            random.choice(unsupported) if unsupported else None
        ),
    }


def search_node(state: ResearchState) -> dict:
    skills = _resolve_research_skills(state)
    result = research_agent.invoke(
        {"messages": [
            HumanMessage(content=(
                f"Company: {state['company']}\n"
                f"Requirement: {state['requirement']}\n"
                f"Met when: {state['positive_when']}\n"
                f"Not met when: {state['negative_when']}\n"
                f"Does not count:\n{_format_does_not_count(state.get('does_not_count'))}"
            ))],
            "tool_call_count": 0,
            "search_documents": {},
            "search_queries_used": [],
            "company": state["company"],
            "requirement": state["requirement"],
            "positive_when": state["positive_when"],
            "negative_when": state["negative_when"],
            "does_not_count": state.get("does_not_count") or [],
            "skills": skills,
            "verified_evidence": [],
            "failed_evidence_checks": [],
            "verifier_judgments": [],
            "unclear_ownership_judgments": [],
            "batch_result_id_match_failures": 0,
            "off_target_company_rejections": 0,
            "off_target_rejections": [],
            "duplicate_search_result_skips": 0,
            "duplicate_claim_skips": 0,
            "empty_evidence_tool_calls": 0,
            "url_selector_extract_attempts": 0,
            "url_selector_full_page_extracts": 0,
            "url_selector_extract_failures": 0,
            "url_selector_decisions": [],
            "query_generator_decisions": [],
            "evidence_extractor_decisions": [],
            "research_agent_steps": [],
            "evidence_full_page_extracts": 0,
        },
        config={"recursion_limit": 12},
    )
    structured_response: ResearchResult = result["structured_response"]
    verified_evidence = result.get("verified_evidence", [])
    verifier_judgments = result.get("verifier_judgments", [])
    return {
        "skills": skills,
        "verified_evidence": verified_evidence,
        "verified_claims": _evidence_claims(verified_evidence),
        "failed_evidence_checks": result.get("failed_evidence_checks", []),
        # VerifierJudgment: claim, title, url, source_content, about_this_company, support, reason, supporting_passages
        "verifier_judgments": verifier_judgments,
        **_sample_verifier_judgments(verifier_judgments),
        # UnclearOwnershipJudgment: claim, title, url, snippet
        "unclear_ownership_judgments": result.get("unclear_ownership_judgments", []),
        "sufficient": structured_response.sufficient,
        "satisfied": structured_response.satisfied,
        "additional_evidence_needed": structured_response.additional_evidence_needed,
        "sufficient_reason": structured_response.reason,
        "search_tool_call_count": result.get("tool_call_count", 0),
        "search_documents": result.get("search_documents", {}),
        "search_queries_used": result.get("search_queries_used", []),
        "batch_result_id_match_failures": result.get("batch_result_id_match_failures", 0),
        "off_target_company_rejections": result.get("off_target_company_rejections", 0),
        "off_target_rejections": result.get("off_target_rejections", []),
        "duplicate_search_result_skips": result.get("duplicate_search_result_skips", 0),
        "duplicate_claim_skips": result.get("duplicate_claim_skips", 0),
        "empty_evidence_tool_calls": result.get("empty_evidence_tool_calls", 0),
        "url_selector_extract_attempts": result.get("url_selector_extract_attempts", 0),
        "url_selector_full_page_extracts": result.get("url_selector_full_page_extracts", 0),
        "url_selector_extract_failures": result.get("url_selector_extract_failures", 0),
        # UrlSelectorDecision (storage shards; LLM still saw all candidates): search_focus, search_query, candidates[{title,url,content}], selections[{url,reason}]
        "url_selector_decisions": result.get("url_selector_decisions", []),
        # QueryGeneratorDecision: search_focus, prior_verified_claims, prior_source_urls, query
        "query_generator_decisions": result.get("query_generator_decisions", []),
        # EvidenceExtractorDecision (one per char-budgeted micro-batch): search_focus, search_query, requirement_id, prior_verified_claims, documents[{result_id,title,url,content,full_page}], extracted[{claim,result_id,source_excerpts}]
        "evidence_extractor_decisions": result.get("evidence_extractor_decisions", []),
        # ResearchAgentStep: search_focus, evidence_received
        "research_agent_steps": result.get("research_agent_steps", []),
        "evidence_full_page_extracts": result.get("evidence_full_page_extracts", 0),
    }

def search_to_fit_score(state: OverallState):
    """Route to fit scoring only when the property gathered enough information."""
    if state.get("sufficient"):
        return "fit_scoring"
    return "END"

def fit_scoring_node(state: FitScoreInput) -> FitScoreUpdate:
    satisfied = state.get("satisfied")
    claims = state.get("verified_claims") or _evidence_claims(
        state.get("verified_evidence")
    )
    result: FitScoreResult = structured_fit_score_llm.invoke([
        SystemMessage(content=FIT_SCORING_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {state['company']}\n"
            f"Requirement: {state['requirement']}\n"
            f"Research decision: satisfied={satisfied}\n"
            f"Verified evidence:\n" + "\n".join(f"- {claim}" for claim in claims)
        )),
    ])
    return {
        "fit_passed": bool(satisfied),
        "fit_score": result.score,
        "fit_reason": result.reason,
    }


async def find_RFP_node(state: RFPInput) -> RFPUpdate:
    agent = await get_rfp_agent()
    website = (state.get("company_website") or "").strip()
    result = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(content=(
                    f"Hotel: {state['company']}\n"
                    f"Official website: {website or 'unknown'}"
                ))
            ],
            "fallback_email": None,
        },
        config={"recursion_limit": 32},
    )
    structured: RfpResult = result["structured_response"]
    return {
        "rfp_url": structured.rfp_url,
        "rfp_summary": structured.summarization,
        "fallback_email": result.get("fallback_email"),
    }


def fit_score_to_contact_discovery(state: OverallState):
    """Route to contact discovery only when the property passed the requirement."""
    if state.get("fit_passed"):
        return "contact_discovery"
    return "END"


def contact_discovery_node(state: FitScoreInput) -> FitScoreUpdate:
    
    return {
        "passed": result.passed,
        "fit_score": result.score,
        "reason": result.reason,
    }