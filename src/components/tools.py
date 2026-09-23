from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

from components.constants import (
    MAX_RESULTS_PER_SEARCH,
    MAX_SEARCH_CALLS,
    MAX_URL_SELECTOR_EXTRACTS,
    TAVILY_MAX_RESULTS,
)
from components.evidence_verification import merge_verification_updates, verify_evidence_item
from components.state import ResearchAgentState
from schemas.research_schemas import OffTargetRejection, SearchDocument
from services.search_evidence_extractor import (
    document_mentions_company,
    extract_evidence_from_search_batch,
    missing_company_tokens,
)
from services.tavily_extract import extract_page_content
from services.query_generator import generate_search_query
from services.url_selector import filter_valid_selections, select_urls_for_full_extract

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


def _collect_prior_queries(
    search_queries_used: list[str] | None,
    search_documents: dict[str, SearchDocument],
) -> list[str]:
    prior_queries: list[str] = []
    seen: set[str] = set()
    for query in search_queries_used or []:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            prior_queries.append(normalized)
    for document in search_documents.values():
        normalized = document["query"].strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            prior_queries.append(normalized)
    return prior_queries


def _collect_prior_source_urls(search_documents: dict[str, SearchDocument]) -> list[str]:
    return sorted({document["url"] for document in search_documents.values()})


def _build_known_document_indexes(
    prior_search_documents: dict[str, SearchDocument],
) -> tuple[dict[str, str], set[str]]:
    known_documents: dict[str, str] = {}
    full_page_urls: set[str] = set()
    for document in prior_search_documents.values():
        url = document["url"]
        known_documents[url] = document["content"]
        if document.get("full_page"):
            full_page_urls.add(url)
    return known_documents, full_page_urls


def _is_duplicate_document(
    url: str,
    content: str,
    *,
    known_documents: dict[str, str],
    full_page_urls: set[str],
) -> bool:
    if url in full_page_urls:
        return True
    return url in known_documents and known_documents[url] == content


def _document_from_result(item: dict, *, query: str, search_focus: str) -> SearchDocument:
    return {
        "query": query,
        "search_focus": search_focus,
        "title": item["title"],
        "url": item["url"],
        "content": item["content"],
        "full_page": False,
    }


def _filter_eligible_results(
    results: list[dict],
    *,
    query: str,
    search_focus: str,
    company: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
) -> tuple[list[SearchDocument], int, list[OffTargetRejection]]:
    eligible: list[SearchDocument] = []
    skipped_duplicate_results = 0
    off_target_rejections: list[OffTargetRejection] = []

    for item in results:
        url = item["url"]
        content = item["content"]
        if _is_duplicate_document(
            url,
            content,
            known_documents=known_documents,
            full_page_urls=full_page_urls,
        ):
            skipped_duplicate_results += 1
            continue

        document = _document_from_result(item, query=query, search_focus=search_focus)
        if not document_mentions_company(document, company):
            off_target_rejections.append({
                "query": query,
                "search_focus": search_focus,
                "title": document["title"],
                "url": url,
                "missing_tokens": missing_company_tokens(document, company),
            })
            continue

        eligible.append(document)

    return eligible, skipped_duplicate_results, off_target_rejections


def _apply_url_selector_full_extracts(
    eligible_documents: list[SearchDocument],
    *,
    company: str,
    requirement: str,
    search_query: str,
    search_focus: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
) -> tuple[list[SearchDocument], int, int, int]:
    selector_candidates = [
        document
        for document in eligible_documents
        if document["url"] not in full_page_urls
    ]
    if not selector_candidates:
        return eligible_documents, 0, 0, 0

    selection_result = select_urls_for_full_extract(
        company=company,
        requirement=requirement,
        search_focus=search_focus,
        search_query=search_query,
        candidates=selector_candidates,
    )
    allowed_urls = {document["url"] for document in selector_candidates}
    selections = filter_valid_selections(
        selection_result,
        allowed_urls=allowed_urls,
        max_selections=MAX_URL_SELECTOR_EXTRACTS,
    )

    full_content_by_url: dict[str, str] = {}
    extract_attempts = 0
    extract_failures = 0

    for url, _reason in selections:
        extract_attempts += 1
        if url in full_page_urls:
            full_content_by_url[url] = known_documents[url]
            continue
        try:
            full_content_by_url[url] = extract_page_content(url)
        except RuntimeError:
            extract_failures += 1
            continue
        full_page_urls.add(url)
        known_documents[url] = full_content_by_url[url]

    if not full_content_by_url:
        return eligible_documents, extract_attempts, 0, extract_failures

    updated_documents: list[SearchDocument] = []
    for document in eligible_documents:
        url = document["url"]
        if url not in full_content_by_url:
            updated_documents.append(document)
            continue
        updated_documents.append({
            **document,
            "content": full_content_by_url[url],
            "full_page": True,
        })

    successful_extracts = len(full_content_by_url)
    return updated_documents, extract_attempts, successful_extracts, extract_failures


def _prioritize_selected_urls(
    eligible_documents: list[SearchDocument],
    selected_urls: set[str],
) -> list[SearchDocument]:
    if not selected_urls:
        return eligible_documents
    selected = [document for document in eligible_documents if document["url"] in selected_urls]
    others = [document for document in eligible_documents if document["url"] not in selected_urls]
    return [*selected, *others]


def _take_extraction_batch(
    eligible_documents: list[SearchDocument],
    *,
    tool_call_id: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
) -> dict[str, SearchDocument]:
    """Keep the top-ranked eligible documents; lower-ranked ones are dropped unextracted."""
    batch_documents: dict[str, SearchDocument] = {}

    for document in eligible_documents[:MAX_RESULTS_PER_SEARCH]:
        url = document["url"]
        if url not in full_page_urls:
            known_documents[url] = document["content"]
        result_id = f"{tool_call_id}_{len(batch_documents)}"
        batch_documents[result_id] = document

    return batch_documents


def _collect_search_batch(
    results: list[dict],
    *,
    query: str,
    search_focus: str,
    company: str,
    requirement: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
    tool_call_id: str,
) -> tuple[
    dict[str, SearchDocument],
    int,
    list[OffTargetRejection],
    int,
    int,
    int,
]:
    eligible, skipped_duplicate_results, off_target_rejections = _filter_eligible_results(
        results,
        query=query,
        search_focus=search_focus,
        company=company,
        known_documents=known_documents,
        full_page_urls=full_page_urls,
    )

    (
        eligible,
        url_selector_extract_attempts,
        url_selector_full_page_extracts,
        url_selector_extract_failures,
    ) = _apply_url_selector_full_extracts(
        eligible,
        company=company,
        requirement=requirement,
        search_query=query,
        search_focus=search_focus,
        known_documents=known_documents,
        full_page_urls=full_page_urls,
    )
    selected_urls = {
        document["url"]
        for document in eligible
        if document.get("full_page")
    }
    eligible = _prioritize_selected_urls(eligible, selected_urls)

    batch_documents = _take_extraction_batch(
        eligible,
        tool_call_id=tool_call_id,
        known_documents=known_documents,
        full_page_urls=full_page_urls,
    )

    return (
        batch_documents,
        skipped_duplicate_results,
        off_target_rejections,
        url_selector_extract_attempts,
        url_selector_full_page_extracts,
        url_selector_extract_failures,
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
def research_search(
    search_focus: str,
    runtime: ToolRuntime[ResearchAgentState],
) -> dict:
    """Run a focused evidence search. Provide search_focus only; retrieval query is generated automatically."""
    prior_search_documents = runtime.state.get("search_documents") or {}
    company = runtime.state.get("company", "")
    requirement = runtime.state.get("requirement", "")
    prior_verified = runtime.state.get("verified_evidence") or []
    prior_verified_claims = [item.claim for item in prior_verified]
    prior_queries = _collect_prior_queries(
        runtime.state.get("search_queries_used"),
        prior_search_documents,
    )
    prior_source_urls = _collect_prior_source_urls(prior_search_documents)

    generated = generate_search_query(
        company=company,
        requirement=requirement,
        search_focus=search_focus,
        prior_verified_claims=prior_verified_claims,
        prior_queries=prior_queries,
        prior_source_urls=prior_source_urls,
    )
    query = generated.query.strip()

    response = tavily_client.search(query, max_results=TAVILY_MAX_RESULTS)
    known_documents, full_page_urls = _build_known_document_indexes(prior_search_documents)
    (
        search_documents,
        skipped_duplicate_results,
        off_target_rejections,
        url_selector_extract_attempts,
        url_selector_full_page_extracts,
        url_selector_extract_failures,
    ) = _collect_search_batch(
        response["results"],
        query=query,
        search_focus=search_focus,
        company=company,
        requirement=requirement,
        known_documents=known_documents,
        full_page_urls=full_page_urls,
        tool_call_id=runtime.tool_call_id,
    )

    all_search_documents = {**prior_search_documents, **search_documents}

    merged_verification, result_id_match_failures, duplicate_claim_skips = _extract_and_verify_batch(
        search_documents,
        company=company,
        collaboration_intent=runtime.state.get("collaboration_intent", ""),
        requirement=requirement,
        search_query=query,
        search_focus=search_focus,
        prior_verified_evidence=prior_verified,
        all_search_documents=all_search_documents,
    )

    verified_batch = merged_verification.get("verified_evidence") or []
    empty_evidence_tool_calls = 1 if search_documents and not verified_batch else 0

    searches_used = runtime.state.get("tool_call_count", 0) + 1
    result_string = _format_tool_message_for_agent(
        searches_used=searches_used,
        verified_batch=verified_batch,
    )

    update: dict = {
        "tool_call_count": 1,
        "search_queries_used": [query] if query else [],
        "search_documents": search_documents,
        "batch_result_id_match_failures": result_id_match_failures,
        "off_target_company_rejections": len(off_target_rejections),
        "off_target_rejections": off_target_rejections,
        "duplicate_search_result_skips": skipped_duplicate_results,
        "duplicate_claim_skips": duplicate_claim_skips,
        "empty_evidence_tool_calls": empty_evidence_tool_calls,
        "url_selector_extract_attempts": url_selector_extract_attempts,
        "url_selector_full_page_extracts": url_selector_full_page_extracts,
        "url_selector_extract_failures": url_selector_extract_failures,
        "messages": [
            ToolMessage(
                content=result_string,
                tool_call_id=runtime.tool_call_id,
            )
        ],
    }
    update.update(merged_verification)

    return Command(update=update)
