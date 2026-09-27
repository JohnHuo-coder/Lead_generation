from __future__ import annotations

import re
import unicodedata

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
    "at least 20",
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
_FUNCTION_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on"}
_WEAK_COMPANY_TOKENS = {
    "building",
    "centre",
    "center",
    "city",
    "garden",
    "grand",
    "house",
    "inn",
    "lodge",
    "night",
    "park",
    "place",
    "plaza",
    "point",
    "residence",
    "room",
    "station",
    "suite",
    "suites",
    "tower",
}
_PARENT_SEGMENT_STOP_TOKENS = _GENERIC_COMPANY_TOKENS | {"soi", "thailand"}
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_SUBWORD_PATTERN = re.compile(r"\d+|[a-z]+")


def _normalize_tokens_source(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokenize(text: str) -> list[str]:
    """Whole alphanumeric runs only, so a name like `S15` is never split into `s` and
    `15` and reduced to a token that matches almost any page."""
    return _WORD_PATTERN.findall(_normalize_tokens_source(text))


def _strip_parent_segment(tokens: list[str]) -> list[str]:
    """Drop the parent company named after `by`, which on-target pages often omit:
    a cvent entry for `INNSiDE by Melia Bangkok Sukhumvit` may only say `INNSIDE`.
    The property's own address resumes at the first generic or numeric token."""
    if "by" not in tokens:
        return tokens

    index = tokens.index("by")
    tail = tokens[index + 1:]
    cursor = 0
    while cursor < len(tail) and not (
        tail[cursor] in _PARENT_SEGMENT_STOP_TOKENS or tail[cursor].isdigit()
    ):
        cursor += 1
    return tokens[:index] + tail[cursor:]


def _company_tokens(company: str) -> set[str]:
    return {
        token
        for token in _strip_parent_segment(_tokenize(company))
        if token not in _GENERIC_COMPANY_TOKENS and token not in _FUNCTION_WORDS
    }


def _is_distinctive_token(token: str) -> bool:
    if token.isdigit() or token in _WEAK_COMPANY_TOKENS:
        return False
    if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
        return True
    return len(token) >= 5


def _company_name_phrase(company: str) -> list[str]:
    """Full property name minus parent-company and function words, kept as a phrase
    so `Night Hotel Building 2` cannot match a page that merely says team building."""
    return [
        token
        for token in _strip_parent_segment(_tokenize(company))
        if token not in _FUNCTION_WORDS
    ]


def _name_phrase_appears(company: str, document: SearchDocument) -> bool:
    phrase = _company_name_phrase(company)
    if not phrase:
        return False
    runs = _document_runs(document)
    width = len(phrase)
    if any(runs[index:index + width] == phrase for index in range(len(runs) - width + 1)):
        return True
    glued = "".join(phrase)
    return any(glued in run for run in _document_url_runs(document))


def _requires_name_phrase(company_tokens: set[str]) -> bool:
    return bool(company_tokens) and not any(
        _is_distinctive_token(token) for token in company_tokens
    )


def _document_runs(document: SearchDocument) -> list[str]:
    return _tokenize(
        " ".join([document["title"], document["url"], document["content"]])
    )


def _document_url_runs(document: SearchDocument) -> list[str]:
    return _tokenize(document["url"])


def _document_tokens(document: SearchDocument) -> set[str]:
    """Each run also contributes its letter/digit parts, because url slugs run words
    together: `sukhumvit20` must satisfy a required `20`, and an underscore-joined
    `maitria_hotel_sukhumvit_18_bangkok_a_chatrium_collection` a required `chatrium`."""
    tokens: set[str] = set()
    for run in _document_runs(document):
        tokens.add(run)
        tokens.update(_SUBWORD_PATTERN.findall(run))
    return tokens


def _token_appears_in_document(token: str, document: SearchDocument) -> bool:
    """A brand token glued into a hostname (`movenpickbangkoksukhumvit15`) still counts.
    Substring matching is URL-only, so title words like `teambuilding` do not satisfy
    `building`. Short tokens and bare numbers never substring-match."""
    tokens = _document_tokens(document)
    if token in tokens:
        return True
    if token.isdigit() or len(token) < 4:
        return False
    return any(token in run for run in _document_url_runs(document))


def _document_mentions_company(
    company_tokens: set[str],
    document: SearchDocument,
    company: str,
) -> bool:
    if not company_tokens:
        return False
    if not all(_token_appears_in_document(token, document) for token in company_tokens):
        return False
    if _requires_name_phrase(company_tokens):
        return _name_phrase_appears(company, document)
    return True


def document_mentions_company(document: SearchDocument, company: str) -> bool:
    return _document_mentions_company(_company_tokens(company), document, company)


def missing_company_tokens(document: SearchDocument, company: str) -> list[str]:
    """Company-name tokens the document never mentions, i.e. why it was off-target."""
    company_tokens = _company_tokens(company)
    if not company_tokens:
        return []
    missing = sorted(
        token
        for token in company_tokens
        if not _token_appears_in_document(token, document)
    )
    if missing:
        return missing
    if _requires_name_phrase(company_tokens) and not _name_phrase_appears(company, document):
        return [" ".join(_company_name_phrase(company))]
    return []


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
