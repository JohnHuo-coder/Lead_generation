from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

from components.constants import MAX_SEARCH_CALLS
from components.evidence_verification import merge_verification_updates, verify_evidence_item
from components.state import ResearchAgentState
from services.search_evidence_extractor import extract_evidence_from_search_batch

tavily_client = TavilyClient()


def _format_verification_summary(
    *,
    verified_batch: list,
    failed_batch: list[dict],
    verified_so_far: list,
) -> str:
    lines: list[str] = []
    if verified_batch:
        lines.append("Verified from this batch:")
        lines.extend(f"- {item.claim}" for item in verified_batch)
    if failed_batch:
        lines.append("Rejected from this batch:")
        for failure in failed_batch:
            lines.append(
                f"- {failure.get('claim')} ({failure.get('failure_reason')})"
            )
    if verified_so_far:
        unique_verified: list = []
        seen_keys: set[tuple[str, str]] = set()
        for item in verified_so_far:
            key = (item.url, " ".join(item.claim.split()).casefold())
            if key not in seen_keys:
                unique_verified.append(item)
                seen_keys.add(key)
        lines.append(f"Verified evidence so far ({len(unique_verified)}):")
        lines.extend(f"- {item.claim}" for item in unique_verified)
    if not lines:
        lines.append("No verified evidence from this batch.")
    return "\n".join(lines)


@tool
def web_search(query: str, runtime: ToolRuntime[ResearchAgentState]) -> dict:
    """Search the web for pages about a company and return source URLs and excerpts."""
    response = tavily_client.search(query, max_results=5)
    prior_search_documents = runtime.state.get("search_documents") or {}
    prior_urls = {document["url"] for document in prior_search_documents.values()}
    search_documents = {}
    result_index_lines = []
    skipped_duplicate_count = 0
    current_urls: set[str] = set()
    for item in response["results"]:
        url = item["url"]
        if url in prior_urls or url in current_urls:
            skipped_duplicate_count += 1
            continue
        current_urls.add(url)
        result_id = f"{runtime.tool_call_id}_{len(search_documents)}"
        document = {
            "query": query,
            "title": item["title"],
            "url": url,
            "content": item["content"],
        }
        search_documents[result_id] = document
        result_index_lines.append(
            f"- result_id={result_id} | title={document['title']} | url={document['url']}"
        )

    all_search_documents = {**prior_search_documents, **search_documents}
    if search_documents:
        batch_evidence, result_id_match_failures = extract_evidence_from_search_batch(
            company=runtime.state.get("company", ""),
            collaboration_intent=runtime.state.get("collaboration_intent", ""),
            requirement=runtime.state.get("requirement", ""),
            batch_documents=search_documents,
        )
        verification_updates = [
            verify_evidence_item(
                evidence,
                company=runtime.state.get("company", ""),
                search_documents=all_search_documents,
            )
            for evidence in batch_evidence
        ]
    else:
        result_id_match_failures = 0
        verification_updates = []

    merged_verification = merge_verification_updates(
        verification_updates,
        runtime.state.get("verified_evidence") or [],
    )
    verified_batch = merged_verification.get("verified_evidence") or []
    failed_batch = merged_verification.get("failed_evidence_checks") or []
    verified_so_far = [
        *(runtime.state.get("verified_evidence") or []),
        *verified_batch,
    ]

    verification_summary = _format_verification_summary(
        verified_batch=verified_batch,
        failed_batch=failed_batch,
        verified_so_far=verified_so_far,
    )
    prior_url_list = ", ".join(sorted(prior_urls)) or "none"
    result_string = (
        f"Search query: {query}\n"
        f"Searches used: {runtime.state.get('tool_call_count', 0) + 1} / {MAX_SEARCH_CALLS}\n"
        f"Skipped duplicate results: {skipped_duplicate_count}\n"
        f"Previously mined URLs: {prior_url_list}\n"
        f"Results:\n"
        f"{chr(10).join(result_index_lines) or '- No new results'}\n\n"
        f"{verification_summary}"
    )

    update: dict = {
        "tool_call_count": 1,
        "search_documents": all_search_documents,
        "batch_result_id_match_failures": result_id_match_failures,
        "messages": [
            ToolMessage(
                content=result_string,
                tool_call_id=runtime.tool_call_id,
            )
        ],
    }
    update.update(merged_verification)

    return Command(update=update)
