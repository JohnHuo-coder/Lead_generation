from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents.middleware import (
    wrap_model_call,
    ModelRequest,
    ModelResponse,
)
from collections.abc import Callable

from components.state import ResearchState, FitScoreState, ResearchAgentState
from schemas.research_schemas import ResearchResult
from schemas.fit_scoring_schemas import FitScoreResult
from components.tools import web_search
from prompts.system_prompts import (
    FIT_SCORING_SYSTEM_PROMPT,
    RESEARCH_AGENT_SYSTEM_PROMPT,
    RESEARCH_FINAL_HUMAN_REMINDER,
    RESEARCH_FINAL_SYSTEM_PROMPT,
)
from llm.models import (
    llm,
    structured_fit_score_llm,
)
from components.constants import MAX_SEARCH_CALLS


@wrap_model_call
def control_web_search(
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
        if tool.name != "web_search"
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
    tools=[web_search],
    middleware=[control_web_search],
    response_format=ToolStrategy(ResearchResult),
    state_schema=ResearchAgentState,
    system_prompt=RESEARCH_AGENT_SYSTEM_PROMPT,
)


def search_node(state: ResearchState) -> dict:
    remaining = state.get("additional_evidence_needed") or []
    focus = "; ".join(remaining) if remaining else state["requirement"]
    result = research_agent.invoke(
        {"messages": [
            HumanMessage(content=(
                f"Company: {state['company']}\n"
                f"Collaboration intent: {state['collaboration_intent']}\n"
                f"Requirement: {state['requirement']}\n"
                f"Current research focus: {focus}"
            ))],
            "tool_call_count": 0,
            "search_documents": {},
            "company": state["company"],
            "collaboration_intent": state["collaboration_intent"],
            "requirement": state["requirement"],
            "verified_evidence": [],
            "failed_evidence_checks": [],
            "batch_result_id_match_failures": 0,
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
        "search_tool_call_count": result.get("tool_call_count", 0),
        "search_documents": result.get("search_documents", {}),
        "batch_result_id_match_failures": result.get("batch_result_id_match_failures", 0),
        "excerpt_derivation_checks": result.get("excerpt_derivation_checks", 0),
        "evidence_full_snippet_verifications": result.get("evidence_full_snippet_verifications", 0),
        "evidence_full_page_extracts": result.get("evidence_full_page_extracts", 0),
    }


def fit_score_node(state: ResearchState) -> FitScoreState:
    result: FitScoreResult = structured_fit_score_llm.invoke([
        SystemMessage(content=FIT_SCORING_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {state['company']}\n"
            f"Collaboration intent: {state['collaboration_intent']}\n"
            f"Requirement: {state['requirement']}\n"
            f"Verified evidence:\n" + "\n".join(
                f"- {e.claim}"
                for e in state.get("verified_evidence", [])
            )
        )),
    ])
    return {
        "fit_score": result.score,
        "reason": result.reason,
        "supporting_facts": result.supporting_facts,
    }


def check_qualified(state: FitScoreState):
    """Determine if the company is qualified for the requirement based on the fit score."""
    fit_score = state.get("fit_score", 0)
    if fit_score >= 75:
        return "contact_discovery"
    else:
        return "END"
