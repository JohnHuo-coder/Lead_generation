from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_url_selector_llm
from prompts.system_prompts import URL_SELECTOR_SYSTEM_PROMPT
from schemas.research_schemas import SearchDocument, UrlSelectorResult


def _format_candidates(documents: list[SearchDocument]) -> str:
    blocks: list[str] = []
    for index, document in enumerate(documents, start=1):
        blocks.append(
            f"candidate_{index}\n"
            f"url: {document['url']}\n"
            f"title: {document['title']}\n"
            f"content: {document['content']}"
        )
    return "\n\n---\n\n".join(blocks)


def select_urls_for_full_extract(
    *,
    company: str,
    requirement: str,
    search_focus: str,
    search_query: str,
    candidates: list[SearchDocument],
) -> UrlSelectorResult:
    if not candidates:
        return UrlSelectorResult(selections=[])

    return structured_url_selector_llm.invoke([
        SystemMessage(content=URL_SELECTOR_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Requirement: {requirement}\n"
            f"Search focus: {search_focus}\n"
            f"Search query: {search_query}\n\n"
            f"Candidates:\n{_format_candidates(candidates)}"
        )),
    ])


def filter_valid_selections(
    result: UrlSelectorResult,
    *,
    allowed_urls: set[str],
    max_selections: int,
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    selections: list[tuple[str, str]] = []
    for choice in result.selections:
        url = choice.url.strip()
        if not url or url not in allowed_urls or url in seen:
            continue
        seen.add(url)
        selections.append((url, choice.reason))
        if len(selections) >= max_selections:
            break
    return selections
