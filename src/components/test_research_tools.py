from __future__ import annotations

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command
from tavily import TavilyClient

from components.constants import TEST_RESEARCH_SEARCH_RESULTS
from components.state import TestResearchAgentState
from schemas.test_research_schemas import (
    CandidateEvidence,
    FailedEvidence,
    TestEvidence,
    TestSearchDocument,
    VerifierJudgment,
)
from services.test_research_extract import extract_page_evidence
from services.test_research_verify import merge_verified_evidence, verify_three_steps
from services.tavily_extract import extract_page_content

tavily_client = TavilyClient()


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def _format_search_results(documents: dict[str, TestSearchDocument]) -> str:
    blocks = []
    for result_id, document in documents.items():
        blocks.append(
            f"result_id: {result_id}\n"
            f"title: {document['title']}\n"
            f"url: {document['url']}\n"
            f"snippet: {document['content']}"
        )
    return "\n\n---\n\n".join(blocks) if blocks else "No search results."


def _format_verified_claims(verified: list[TestEvidence]) -> str:
    if not verified:
        return "- none"
    return "\n".join(f"- {item.claim}" for item in verified)


@tool
def web_search(
    query: str,
    runtime: ToolRuntime[None, TestResearchAgentState],
) -> Command:
    """Search the web for pages about the target company.

    Use a short keyword query. Results include result_id, title, url, and snippet.
    If a snippet already supports a required fact, call write_evidence.
    If the snippet is too thin, inspect that result_id instead.
    """
    response = tavily_client.search(
        query.strip(),
        max_results=TEST_RESEARCH_SEARCH_RESULTS,
    )
    documents: dict[str, TestSearchDocument] = {}
    for index, item in enumerate(response.get("results") or []):
        result_id = f"{runtime.tool_call_id}_{index}"
        documents[result_id] = {
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "content": item.get("content") or "",
        }

    return Command(
        update={
            "search_documents": documents,
            "search_queries_used": [query.strip()] if query.strip() else [],
            "web_search_count": 1,
            "messages": [
                ToolMessage(
                    content=_format_search_results(documents),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


@tool
def inspect_web_page(
    result_id: str,
    research_focus: str,
    runtime: ToolRuntime[None, TestResearchAgentState],
) -> Command:
    """Extract one previous web_search result and pull evidence for this research_focus.

    Use after web_search when a snippet is not enough. Pass the result_id.
    Verified claims are saved automatically. Do not write_evidence afterward.
    Do not inspect the same page twice.
    """
    search_documents = runtime.state.get("search_documents") or {}
    document = search_documents.get(result_id)
    if document is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"result_id {result_id} is not in search_documents. "
                            "Inspect a result_id from a previous web_search."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    normalized = _normalize_url(document["url"])
    inspected = runtime.state.get("inspected_urls") or {}
    if normalized in inspected:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"Already inspected {normalized}. "
                            "Do not inspect this page again. Use a different result_id "
                            "or write_evidence from a search snippet."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    try:
        content = extract_page_content(normalized)
    except RuntimeError as exc:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Failed to extract {normalized}: {exc}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    company = runtime.state.get("company", "")
    prior_verified = runtime.state.get("verified_evidence") or []
    updated_document: TestSearchDocument = {
        "title": document["title"],
        "url": document["url"],
        "content": content,
    }
    batch_documents = {result_id: updated_document}

    extracted = extract_page_evidence(
        company=company,
        research_focus=research_focus,
        url=normalized,
        content=content,
        prior_verified_claims=[item.claim for item in prior_verified],
    )

    if not extracted:
        return Command(
            update={
                "search_documents": batch_documents,
                "inspected_urls": {normalized: True},
                "messages": [
                    ToolMessage(
                        content=(
                            f"Inspected {result_id} ({normalized}). "
                            f"No evidence related to research focus: {research_focus}."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    verified_items: list[TestEvidence] = []
    failed_items: list[FailedEvidence] = []
    judgments: list[VerifierJudgment] = []
    for item in extracted:
        outcome = verify_three_steps(
            claim=item.claim,
            result_id=result_id,
            company=company,
            search_documents=batch_documents,
        )
        if outcome.judgment is not None:
            judgments.append(outcome.judgment)
        if outcome.failed is not None:
            failed_items.append(outcome.failed)
            continue
        if outcome.evidence is not None:
            verified_items.append(outcome.evidence)

    accepted = merge_verified_evidence(verified_items, prior_verified)
    if accepted:
        message = (
            f"Inspected {result_id} ({normalized}). Verified evidence:\n"
            + _format_verified_claims(accepted)
        )
    else:
        message = (
            f"Inspected {result_id} ({normalized}). "
            f"No verified evidence related to research focus: {research_focus}."
        )

    return Command(
        update={
            "search_documents": batch_documents,
            "inspected_urls": {normalized: True},
            "verified_evidence": accepted,
            "failed_evidence": failed_items,
            "verifier_judgments": judgments,
            "messages": [
                ToolMessage(content=message, tool_call_id=runtime.tool_call_id)
            ],
        }
    )


@tool
def write_evidence(
    candidates: list[CandidateEvidence],
    runtime: ToolRuntime[None, TestResearchAgentState],
) -> Command:
    """Save evidence already visible in a web_search snippet.

    Use this instead of inspect_web_page when the snippet already contains
    the fact. Each candidate needs evidence and result_id.
    Do not write_evidence after inspect_web_page; inspect already saves
    verified claims.
    """
    company = runtime.state.get("company", "")
    search_documents = runtime.state.get("search_documents") or {}
    prior_verified = runtime.state.get("verified_evidence") or []

    verified_items: list[TestEvidence] = []
    failed_items: list[FailedEvidence] = []
    judgments: list[VerifierJudgment] = []
    failed_lines: list[str] = []
    for candidate in candidates:
        outcome = verify_three_steps(
            claim=candidate.evidence,
            result_id=candidate.result_id,
            company=company,
            search_documents=search_documents,
        )
        if outcome.judgment is not None:
            judgments.append(outcome.judgment)
        if outcome.failed is not None:
            failed_items.append(outcome.failed)
            failed_lines.append(f"- {outcome.failed.claim} ({outcome.failed.reason})")
            continue
        if outcome.evidence is not None:
            verified_items.append(outcome.evidence)

    accepted = merge_verified_evidence(verified_items, prior_verified)
    lines = ["Write evidence results:"]
    if accepted:
        lines.append("Verified:")
        lines.extend(f"- {item.claim}" for item in accepted)
    else:
        lines.append("Verified: none")
    if failed_lines:
        lines.append("Failed:")
        lines.extend(failed_lines)

    return Command(
        update={
            "verified_evidence": accepted,
            "failed_evidence": failed_items,
            "verifier_judgments": judgments,
            "messages": [
                ToolMessage(
                    content="\n".join(lines),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Reflect on research progress before another tool call or finishing.

    Use this after web_search, inspect_web_page, or write_evidence.

    Do not call this before a research result.
    Do not call it in parallel with another tool.
    Do not call it twice consecutively.

    The reflection should determine:

    1. What verified evidence was added?
    2. Is it enough to evaluate the requirement?
    3. What specific fact is still missing?
    4. Should the next action be:
       - write_evidence from a snippet already in hand
       - inspect one unused search result
       - search a different angle
       - stop because the requirement can be evaluated
       - stop because a relevant budget is exhausted

    Prefer write_evidence over inspect when the snippet already has the fact.
    Do not inspect a result_id whose page was already inspected.

    This tool records reasoning only. Factual conclusions must come from
    verified evidence in tool results.

    Args:
        reflection: Concise analysis of findings, remaining gap,
            and the best next action.

    Returns:
        Confirmation that the reflection was recorded.
    """

    return "Reflection recorded."
