import re

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents.middleware import (
    wrap_model_call,
    ModelRequest,
    ModelResponse,
)
from collections.abc import Callable
from langgraph.types import Send

from components.state import ResearchState, FitScoreState, ResearchAgentState, CheckSourceExcerptState
from schemas.research_schemas import ResearchResult
from schemas.fit_scoring_schemas import FitScoreResult
from components.tools import web_search
from prompts.system_prompts import (
    FIT_SCORING_SYSTEM_PROMPT,
    RESEARCH_AGENT_SYSTEM_PROMPT,
    VERIFICATION_SYSTEM_PROMPT,
)
from llm.models import llm, structured_fit_score_llm, structured_verification_llm

MAX_SEARCH_CALLS = 4





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

    updated_system_message = SystemMessage(
        content=[
            *request.system_message.content_blocks,
            {
                "type": "text",
                "text": (
                    "The web search budget is exhausted. "
                    "Do not request additional searches. "
                    "Produce the final structured response using only the "
                    "evidence already collected. If the evidence is insufficient, "
                    "set sufficient=false and describe the missing evidence."
                ),
            },
        ]
    )

    return handler(
        request.override(
            tools=remaining_tools,
            system_message=updated_system_message,
            model_settings=model_settings,
        )
    )



research_agent = create_agent(
    model=llm,
    tools=[web_search],
    middleware=[control_web_search],
    response_format=ToolStrategy(ResearchResult),
    state_schema = ResearchAgentState,
    system_prompt=RESEARCH_AGENT_SYSTEM_PROMPT
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
            "search_documents": {}
        },
        config={"recursion_limit": 12},
    )
    structured_response: ResearchResult = result["structured_response"]
    return {"candidate_evidence": structured_response.evidence, 
            "sufficient": structured_response.sufficient, 
            "additional_evidence_needed": structured_response.additional_evidence_needed,
            "search_tool_call_count": result.get("tool_call_count", 0),
            "search_documents": result.get("search_documents", {})}


def continue_to_check_source_excerpts(state: ResearchState):
    search_documents = state["search_documents"]
    return [
        Send(
            "check_source_excerpts",
            {"evidence": evidence, "search_documents": search_documents},
        )
        for evidence in state["candidate_evidence"]
    ]


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _normalize_for_match(text: str) -> str:
    return _normalize_text(text).casefold()


def _excerpt_in_content(excerpt: str, content: str) -> bool:
    normalized_excerpt = _normalize_for_match(excerpt)
    if not normalized_excerpt:
        return False
    return normalized_excerpt in _normalize_for_match(content)


def _build_check_failure(
    evidence,
    *,
    check_stage: str,
    failure_reason: str,
    mismatched_excerpts: list[str] | None = None,
    verification_reason: str = "",
    source_content: str = "",
) -> dict:
    return {
        "failed_evidence_checks": [
            {
                "claim": evidence.claim,
                "result_id": evidence.result_id,
                "url": evidence.url,
                "source_excerpts": evidence.source_excerpts,
                "reason": evidence.reason,
                "check_stage": check_stage,
                "failure_reason": failure_reason,
                "mismatched_excerpts": mismatched_excerpts or [],
                "verification_reason": verification_reason,
                "source_content": source_content,
            }
        ]
    }


def _find_excerpt_span(content: str, excerpt: str) -> tuple[int, int] | None:
    if not excerpt:
        return None

    direct_start = content.find(excerpt)
    if direct_start != -1:
        return direct_start, direct_start + len(excerpt)

    folded_start = content.casefold().find(excerpt.casefold())
    if folded_start != -1:
        return folded_start, folded_start + len(excerpt)

    pattern = re.sub(r"\s+", r"\\s+", re.escape(_normalize_text(excerpt)))
    match = re.search(pattern, content, flags=re.IGNORECASE)
    if match:
        return match.start(), match.end()

    return None


def _extract_context(
    content: str,
    excerpt: str,
    context_chars: int = 300,
) -> str | None:
    span = _find_excerpt_span(content, excerpt)
    if span is None:
        return None

    start, end = span
    left = max(0, start - context_chars)
    right = min(len(content), end + context_chars)
    return content[left:right]


def check_source_excerpts(state: CheckSourceExcerptState) -> ResearchState:
    search_documents = state["search_documents"]
    evidence = state["evidence"]
    result_id = evidence.result_id
    excerpts = evidence.source_excerpts

    if not excerpts:
        return _build_check_failure(
            evidence,
            check_stage="source_excerpt",
            failure_reason="missing_excerpts",
        )

    document = search_documents.get(result_id)
    if not document:
        return _build_check_failure(
            evidence,
            check_stage="source_excerpt",
            failure_reason="invalid_result_id",
            mismatched_excerpts=list(excerpts),
        )

    source_content = document["content"]
    mismatched_excerpts = [
        excerpt
        for excerpt in excerpts
        if not _excerpt_in_content(excerpt, source_content)
    ]
    if mismatched_excerpts:
        return _build_check_failure(
            evidence,
            check_stage="source_excerpt",
            failure_reason="excerpt_not_found",
            mismatched_excerpts=mismatched_excerpts,
            source_content=source_content,
        )

    extended_excerpts: list[str] = []
    context_extraction_failures: list[str] = []
    for excerpt in excerpts:
        context = _extract_context(source_content, excerpt)
        if context is None:
            context_extraction_failures.append(excerpt)
            continue
        extended_excerpts.append(context)

    if context_extraction_failures:
        return _build_check_failure(
            evidence,
            check_stage="source_excerpt",
            failure_reason="context_extraction_failed",
            mismatched_excerpts=context_extraction_failures,
            source_content=source_content,
        )

    formatted_excerpts = "\n\n---\n\n".join(
        f"Excerpt {index + 1}:\n{context}"
        for index, context in enumerate(extended_excerpts)
    )
    verification_result = structured_verification_llm.invoke([
        SystemMessage(content=VERIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Claim: {evidence.claim}\n\n"
            f"Supporting source excerpts with context:\n{formatted_excerpts}"
        )),
    ])

    if not verification_result.support:
        return _build_check_failure(
            evidence,
            check_stage="claim_verification",
            failure_reason="claim_not_supported",
            verification_reason=verification_result.reason,
            source_content=source_content,
        )

    return {"verified_evidence": [evidence]}

                





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