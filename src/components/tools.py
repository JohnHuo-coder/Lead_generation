from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

from components.constants import MAX_SEARCH_CALLS, TAVILY_MAX_RESULTS
from components.evidence_verification import merge_verification_updates, verify_evidence_item
from components.state import ResearchAgentState
from schemas.research_schemas import SearchDocument
from services.search_evidence_extractor import (
    document_mentions_company,
    extract_evidence_from_search_batch,
)

tavily_client = TavilyClient()


def _format_tool_message_for_agent(
    *,
    searches_used: int,
    verified_batch: list,
) -> str:
    lines = [f"Searches used: {searches_used} / {MAX_SEARCH_CALLS}", "", "Verified this search:"]

    if verified_batch:
        lines.extend(f"- {item.claim}" for item in verified_batch)
    else:
        lines.append("- none")
        lines.append("No verified evidence from this search; try a different search angle.")

    return "\n".join(lines)


def _is_duplicate_document(url: str, content: str, known_documents: dict[str, str]) -> bool:
    return url in known_documents and known_documents[url] == content


def _document_from_result(item: dict, *, query: str, search_focus: str) -> SearchDocument:
    return {
        "query": query,
        "search_focus": search_focus,
        "title": item["title"],
        "url": item["url"],
        "content": item["content"],
    }


def _collect_search_batches(
    results: list[dict],
    *,
    query: str,
    search_focus: str,
    company: str,
    known_documents: dict[str, str],
    tool_call_id: str,
) -> tuple[dict[str, SearchDocument], int, int]:
    search_documents: dict[str, SearchDocument] = {}
    skipped_duplicate_results = 0
    off_target_company_rejections = 0

    for item in results:
        url = item["url"]
        content = item["content"]
        if _is_duplicate_document(url, content, known_documents):
            skipped_duplicate_results += 1
            continue

        document = _document_from_result(item, query=query, search_focus=search_focus)
        if not document_mentions_company(document, company):
            off_target_company_rejections += 1
            continue

        if len(search_documents) >= TAVILY_MAX_RESULTS:
            break

        known_documents[url] = content
        result_id = f"{tool_call_id}_{len(search_documents)}"
        search_documents[result_id] = document

    return (
        search_documents,
        skipped_duplicate_results,
        off_target_company_rejections,
    )


def _extract_and_verify_batch(
    batch_documents: dict[str, SearchDocument],
    *,
    company: str,
    collaboration_intent: str,
    requirement: str,
    search_query: str,
    search_focus: str,
    prior_verified_evidence: list,
    all_search_documents: dict[str, SearchDocument],
) -> tuple[dict, int, int]:
    if not batch_documents:
        return {}, 0, 0

    prior_verified_claims = [
        item.claim for item in prior_verified_evidence
    ]
    batch_evidence, result_id_match_failures = extract_evidence_from_search_batch(
        company=company,
        collaboration_intent=collaboration_intent,
        requirement=requirement,
        search_query=search_query,
        search_focus=search_focus,
        prior_verified_claims=prior_verified_claims,
        batch_documents=batch_documents,
    )
    verification_updates = [
        verify_evidence_item(
            evidence,
            company=company,
            search_documents=all_search_documents,
        )
        for evidence in batch_evidence
    ]
    merged_verification, duplicate_claim_skips = merge_verification_updates(
        verification_updates,
        prior_verified_evidence,
    )
    return merged_verification, result_id_match_failures, duplicate_claim_skips


@tool
def web_search(
    query: str,
    search_focus: str,
    runtime: ToolRuntime[ResearchAgentState],
) -> dict:
    """Search the web for sources. query is for retrieval; search_focus guides evidence extraction."""
    response = tavily_client.search(query, max_results=TAVILY_MAX_RESULTS)
    prior_search_documents = runtime.state.get("search_documents") or {}
    known_documents = {
        document["url"]: document["content"]
        for document in prior_search_documents.values()
    }

    company = runtime.state.get("company", "")
    search_documents, skipped_duplicate_results, off_target_company_rejections = _collect_search_batches(
        response["results"],
        query=query,
        search_focus=search_focus,
        company=company,
        known_documents=known_documents,
        tool_call_id=runtime.tool_call_id,
    )

    prior_verified = runtime.state.get("verified_evidence") or []
    all_search_documents = {**prior_search_documents, **search_documents}

    merged_verification, result_id_match_failures, duplicate_claim_skips = _extract_and_verify_batch(
        search_documents,
        company=company,
        collaboration_intent=runtime.state.get("collaboration_intent", ""),
        requirement=runtime.state.get("requirement", ""),
        search_query=query,
        search_focus=search_focus,
        prior_verified_evidence=prior_verified,
        all_search_documents=all_search_documents,
    )

    verified_batch = merged_verification.get("verified_evidence") or []

    searches_used = runtime.state.get("tool_call_count", 0) + 1
    result_string = _format_tool_message_for_agent(
        searches_used=searches_used,
        verified_batch=verified_batch,
    )

    update: dict = {
        "tool_call_count": 1,
        "search_documents": search_documents,
        "batch_result_id_match_failures": result_id_match_failures,
        "off_target_company_rejections": off_target_company_rejections,
        "duplicate_search_result_skips": skipped_duplicate_results,
        "duplicate_claim_skips": duplicate_claim_skips,
        "messages": [
            ToolMessage(
                content=result_string,
                tool_call_id=runtime.tool_call_id,
            )
        ],
    }
    update.update(merged_verification)

    return Command(update=update)
