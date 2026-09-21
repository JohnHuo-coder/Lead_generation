from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

_CAPACITY_FOCUS_HINTS = (
    "capacity",
    "headcount",
    "attendee",
    "guest",
    "pax",
    "seat",
    "size",
    "sqm",
    "sq ft",
    "square",
    "20-60",
    "room types",
    "maximum capacity",
    "max capacity",
)
_CAPACITY_CLAIM_HINTS = (
    "capacity",
    "guest",
    "attendee",
    "people",
    "pax",
    "seat",
    "sqm",
    "sq ft",
    "square meter",
    "square foot",
    "m2",
    "ft2",
)

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


def document_mentions_company(document: SearchDocument, company: str) -> bool:
    return _document_mentions_company(_company_tokens(company), document)


def _focus_requests_capacity(search_focus: str) -> bool:
    focus = search_focus.casefold()
    return any(hint in focus for hint in _CAPACITY_FOCUS_HINTS)


def _claim_addresses_search_focus(claim: str, search_focus: str) -> bool:
    if not _focus_requests_capacity(search_focus):
        return True

    claim_text = claim.casefold()
    has_number = bool(re.search(r"\d", claim))
    has_capacity_word = any(hint in claim_text for hint in _CAPACITY_CLAIM_HINTS)
    if has_number or has_capacity_word:
        return True

    existence_only_patterns = (
        "has a conference room",
        "has meeting",
        "provides meeting",
        "meeting/banquet facilities",
        "offers event spaces",
        "ideal for conferences",
        "banquet halls",
        "meeting rooms",
    )
    return not any(pattern in claim_text for pattern in existence_only_patterns)


def _format_verified_claims(prior_verified_claims: list[str]) -> str:
    if not prior_verified_claims:
        return "- none"
    return "\n".join(f"- {claim}" for claim in prior_verified_claims)


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
    batch_documents: dict[str, SearchDocument],
) -> Evidence | None:
    def _matches_document(result_id: str) -> bool:
        document = batch_documents.get(result_id)
        if document is None:
            return False
        return all(
            _excerpt_in_content(excerpt, document["content"])
            for excerpt in evidence.source_excerpts
        )

    def _resolve(result_id: str) -> Evidence:
        document = batch_documents[result_id]
        return evidence.model_copy(update={"url": document["url"]})

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
        return _resolve(matched_id).model_copy(update={"result_id": matched_id})

    return None


def extract_evidence_from_search_batch(
    *,
    company: str,
    collaboration_intent: str,
    requirement: str,
    search_query: str,
    search_focus: str,
    prior_verified_claims: list[str],
    batch_documents: dict[str, SearchDocument],
) -> tuple[list[Evidence], int]:
    if not batch_documents:
        return [], 0

    result = structured_search_batch_evidence_llm.invoke([
        SystemMessage(content=SEARCH_BATCH_EVIDENCE_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Collaboration intent: {collaboration_intent}\n"
            f"Requirement: {requirement}\n"
            f"Search focus for this batch: {search_focus}\n"
            f"Search query for this batch: {search_query}\n\n"
            f"Already verified claims (do not re-extract):\n"
            f"{_format_verified_claims(prior_verified_claims)}\n\n"
            f"Search results from this search only:\n"
            f"{_format_batch_results(batch_documents)}"
        )),
    ])

    resolved: list[Evidence] = []
    result_id_match_failures = 0
    for item in result.evidence:
        if not _claim_addresses_search_focus(item.claim, search_focus):
            continue
        matched = _resolve_evidence_to_batch(item, batch_documents)
        if matched is not None:
            resolved.append(matched)
        else:
            result_id_match_failures += 1
    return resolved, result_id_match_failures
