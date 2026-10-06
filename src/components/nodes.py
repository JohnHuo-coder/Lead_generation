from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents.middleware import (
    wrap_model_call,
    ModelRequest,
    ModelResponse,
)
from collections.abc import Callable

from components.state import (
    OverallState,
    ResearchState,
    FitScoreInput,
    FitScoreUpdate,
    ResearchAgentState,
    RFPInput,
    RFPUpdate,
    TestResearchInput,
)
from schemas.research_schemas import ResearchResult
from schemas.test_research_schemas import TestResearchResult
from schemas.fit_scoring_schemas import FitScoreResult
from components.constants import MAX_SEARCH_CALLS
from components.tools import research_search
from prompts.fit_scoring import FIT_SCORING_SYSTEM_PROMPT
from prompts.system_prompts import (
    RESEARCH_AGENT_SYSTEM_PROMPT,
    RESEARCH_FINAL_HUMAN_REMINDER,
    RESEARCH_FINAL_SYSTEM_PROMPT,
)
from llm.models import (
    llm,
    structured_fit_score_llm,
)
from schemas.rfp_schemas import RfpResult
from services.rfp_agent import get_rfp_agent
from services.test_research_agent import get_test_research_agent, research_tool_counts


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
            request.override(model_settings=model_settings)
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
            system_message=SystemMessage(content=RESEARCH_FINAL_SYSTEM_PROMPT),
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
    system_prompt=RESEARCH_AGENT_SYSTEM_PROMPT.format(
        max_search_calls=MAX_SEARCH_CALLS,
    ),
)


def search_node(state: ResearchState) -> dict:
    result = research_agent.invoke(
        {"messages": [
            HumanMessage(content=(
                f"Company: {state['company']}\n"
                f"Requirement: {state['requirement']}"
            ))],
            "tool_call_count": 0,
            "search_documents": {},
            "search_queries_used": [],
            "company": state["company"],
            "requirement": state["requirement"],
            "verified_evidence": [],
            "failed_evidence_checks": [],
            "batch_result_id_match_failures": 0,
            "off_target_company_rejections": 0,
            "off_target_rejections": [],
            "duplicate_search_result_skips": 0,
            "duplicate_claim_skips": 0,
            "empty_evidence_tool_calls": 0,
            "url_selector_extract_attempts": 0,
            "url_selector_full_page_extracts": 0,
            "url_selector_extract_failures": 0,
            "excerpt_derivation_checks": 0,
            "evidence_full_snippet_verifications": 0,
            "evidence_full_page_extracts": 0,
        },
        config={"recursion_limit": 12},
    )
    structured_response: ResearchResult = result["structured_response"]
    return {
        "verified_evidence": result.get("verified_evidence", []),
        "failed_evidence_checks": result.get("failed_evidence_checks", []),
        "sufficient": structured_response.sufficient,
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
        "excerpt_derivation_checks": result.get("excerpt_derivation_checks", 0),
        "evidence_full_snippet_verifications": result.get("evidence_full_snippet_verifications", 0),
        "evidence_full_page_extracts": result.get("evidence_full_page_extracts", 0),
    }

def search_to_fit_score(state: OverallState):
    """Route to fit scoring only when the property gathered enough information."""
    if state.get("sufficient"):
        return "fit_scoring"
    return "END"

def fit_scoring_node(state: FitScoreInput) -> FitScoreUpdate:
    result: FitScoreResult = structured_fit_score_llm.invoke([
        SystemMessage(content=FIT_SCORING_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {state['company']}\n"
            f"Requirement: {state['requirement']}\n"
            f"Verified evidence:\n" + "\n".join(
                f"- {e.claim}"
                for e in state.get("verified_evidence", [])
            )
        )),
    ])
    return {
        "fit_passed": result.passed,
        "fit_score": result.score,
        "fit_reason": result.reason,
    }


async def test_research_node(state: TestResearchInput) -> dict:
    agent = await get_test_research_agent()
    result = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(content=(
                    f"Company: {state['company']}\n"
                    f"Requirement: {state['requirement']}"
                ))
            ],
            "company": state["company"],
            "requirement": state["requirement"],
            "search_documents": {},
            "inspected_urls": {},
            "verified_evidence": [],
            "failed_evidence": [],
            "verifier_judgments": [],
            "search_queries_used": [],
            "web_search_count": 0,
        },
        config={"recursion_limit": 48},
    )
    structured: TestResearchResult = result["structured_response"]
    counts = research_tool_counts(result.get("messages") or [])
    return {
        "verified_evidence": result.get("verified_evidence", []),
        "failed_evidence": result.get("failed_evidence", []),
        "verifier_judgments": result.get("verifier_judgments", []),
        "sufficient": structured.sufficient,
        "additional_evidence_needed": structured.additional_evidence_needed,
        "sufficient_reason": structured.reason,
        "search_documents": result.get("search_documents", {}),
        "search_queries_used": result.get("search_queries_used", []),
        "search_tool_call_count": counts["web_search"],
        "inspect_tool_call_count": counts["inspect_web_page"],
        "write_evidence_tool_call_count": counts["write_evidence"],
        "think_tool_call_count": counts["think_tool"],
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