import re

from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

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
        lines.append(f"Verified evidence so far ({len(verified_so_far)}):")
        lines.extend(f"- {item.claim}" for item in verified_so_far)
    if not lines:
        lines.append("No verified evidence from this batch.")
    return "\n".join(lines)


@tool
def web_search(
    query: str,
    runtime: ToolRuntime[ResearchAgentState],
    include_domains: list[str] | None = None,
) -> dict:
    """Search the web; use include_domains for domain restrictions, not search operators."""
    site_domains = re.findall(r"(?<!\S)site:([^\s]+)", query)
    query = re.sub(r"(?<!\S)site:[^\s]+", "", query)
    query = " ".join(query.split())
    domains = list(dict.fromkeys([*(include_domains or []), *site_domains]))
    if domains:
        response = tavily_client.search(
            query,
            max_results=5,
            include_domains=domains,
        )
    else:
        response = tavily_client.search(query, max_results=5)
    search_documents = {}
    result_index_lines = []
    for index, item in enumerate(response["results"]):
        result_id = f"{runtime.tool_call_id}_{index}"
        document = {
            "query": query,
            "title": item["title"],
            "url": item["url"],
            "content": item["content"],
        }
        search_documents[result_id] = document
        result_index_lines.append(
            f"- result_id={result_id} | title={document['title']} | url={document['url']}"
        )

    all_search_documents = {
        **(runtime.state.get("search_documents") or {}),
        **search_documents,
    }
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
    merged_verification = merge_verification_updates(verification_updates)
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
    result_string = (
        f"Search query: {query}\n"
        f"Results:\n"
        f"{chr(10).join(result_index_lines) or '- No results'}\n\n"
        f"{verification_summary}"
    )

    update: dict = {
        "tool_call_count": 1,
        "search_documents": search_documents,
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
