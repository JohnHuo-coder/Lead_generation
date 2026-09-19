from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_search_batch_evidence_llm
from prompts.system_prompts import SEARCH_BATCH_EVIDENCE_PROMPT
from schemas.research_schemas import Evidence, SearchDocument


def _normalize_for_match(text: str) -> str:
    return " ".join(text.split()).casefold()


def _excerpt_in_content(excerpt: str, content: str) -> bool:
    normalized_excerpt = _normalize_for_match(excerpt)
    if not normalized_excerpt:
        return False
    return normalized_excerpt in _normalize_for_match(content)


_GENERIC_COMPANY_TOKENS = {
    "bangkok",
    "hotel",
    "hotels",
    "sukhumvit",
    "the",
}


def _company_tokens(company: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w]+", company.casefold())
        if token not in _GENERIC_COMPANY_TOKENS
    }


def _document_mentions_company(
    company_tokens: set[str],
    document: SearchDocument,
) -> bool:
    document_tokens = set(
        re.findall(
            r"[\w]+",
            " ".join(
                [document["title"], document["url"], document["content"]]
            ).casefold(),
        )
    )
    return bool(company_tokens) and company_tokens <= document_tokens


def _format_batch_results(batch_documents: dict[str, SearchDocument]) -> str:
    blocks: list[str] = []
    for result_id, document in batch_documents.items():
        blocks.append(
            f"result_id: {result_id}\n"
            f"title: {document['title']}\n"
            f"url: {document['url']}\n"
            f"content: {document['content']}"
        )
    return "\n\n---\n\n".join(blocks)


def _resolve_evidence_to_batch(
    evidence: Evidence,
    company: str,
    batch_documents: dict[str, SearchDocument],
) -> tuple[Evidence | None, bool]:
    company_tokens = _company_tokens(company)

    def _matches_document(result_id: str) -> bool:
        document = batch_documents.get(result_id)
        if document is None:
            return False
        return all(
            _excerpt_in_content(excerpt, document["content"])
            for excerpt in evidence.source_excerpts
        )

    def _resolve(result_id: str) -> tuple[Evidence | None, bool]:
        document = batch_documents[result_id]
        if not _document_mentions_company(company_tokens, document):
            return None, True
        return evidence.model_copy(update={"url": document["url"]}), False

    if evidence.result_id in batch_documents and _matches_document(evidence.result_id):
        return _resolve(evidence.result_id)

    # llm usually gives wrong result id, use excerpt in content test to find the right document and its result_id
    matching_ids = [
        result_id
        for result_id in batch_documents
        if _matches_document(result_id)
    ]
    if len(matching_ids) == 1:
        matched_id = matching_ids[0]
        matched, off_target = _resolve(matched_id)
        if matched is not None:
            matched = matched.model_copy(update={"result_id": matched_id})
        return matched, off_target

    return None, False


def extract_evidence_from_search_batch(
    *,
    company: str,
    collaboration_intent: str,
    requirement: str,
    batch_documents: dict[str, SearchDocument],
) -> tuple[list[Evidence], int, int]:
    if not batch_documents:
        return [], 0, 0

    result = structured_search_batch_evidence_llm.invoke([
        SystemMessage(content=SEARCH_BATCH_EVIDENCE_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Collaboration intent: {collaboration_intent}\n"
            f"Requirement: {requirement}\n\n"
            f"Search results from this search only:\n"
            f"{_format_batch_results(batch_documents)}"
        )),
    ])

    resolved: list[Evidence] = []
    result_id_match_failures = 0
    off_target_company_rejections = 0
    for item in result.evidence:
        matched, off_target = _resolve_evidence_to_batch(
            item,
            company,
            batch_documents,
        )
        if matched is not None:
            resolved.append(matched)
        elif off_target:
            off_target_company_rejections += 1
        else:
            result_id_match_failures += 1
    return resolved, result_id_match_failures, off_target_company_rejections
