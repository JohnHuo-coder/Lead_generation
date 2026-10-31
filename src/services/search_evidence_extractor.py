from __future__ import annotations

import re
import unicodedata

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_search_batch_evidence_llm
from prompts.research import SEARCH_BATCH_EVIDENCE_PROMPT
from prompts.rules import with_domain_rules
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
    "studio",
    "suite",
    "suites",
    "tower",
}
# After `by`, skip the parent brand. Resume only at a location or number,
# not at hotel/hotels leftover from "by Kingston Hotels".
_PARENT_RESUME_TOKENS = {"bangkok", "sukhumvit", "soi", "thailand"}
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_SUBWORD_PATTERN = re.compile(r"\d+|[a-z]+")
_HYPHEN_SPLIT_PATTERN = re.compile(r"\s[-–—]\s")


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
        tail[cursor] in _PARENT_RESUME_TOKENS or tail[cursor].isdigit()
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
    return len(token) >= 4


def _company_name_phrase(company: str) -> list[str]:
    """Property tokens minus parent-company, generics, and function words, kept
    in order so `Night Hotel Building 2` cannot match a page that merely says
    team building."""
    return [
        token
        for token in _strip_parent_segment(_tokenize(company))
        if token not in _FUNCTION_WORDS and token not in _GENERIC_COMPANY_TOKENS
    ]


def _title_url_document(document: SearchDocument) -> SearchDocument:
    return {**document, "content": ""}


def _phrase_is_subsequence(phrase: list[str], runs: list[str]) -> bool:
    cursor = 0
    for run in runs:
        if cursor < len(phrase) and run == phrase[cursor]:
            cursor += 1
    return cursor == len(phrase)


def _title_url_token_runs(document: SearchDocument) -> list[str]:
    runs: list[str] = []
    for run in _tokenize(document["title"]) + _document_url_runs(document):
        runs.append(run)
        runs.extend(_SUBWORD_PATTERN.findall(run))
    return runs


def _name_phrase_appears(company: str, document: SearchDocument) -> bool:
    phrase = _company_name_phrase(company)
    if not phrase:
        return False
    runs = _document_runs(document)
    width = len(phrase)
    if any(runs[index:index + width] == phrase for index in range(len(runs) - width + 1)):
        return True
    glued = "".join(phrase)
    if any(glued in run for run in _document_url_runs(document)):
        return True
    if _phrase_is_subsequence(phrase, _title_url_token_runs(document)):
        return True
    title_url = _title_url_document(document)
    glues = _neighbor_glues(company)
    return all(
        _token_appears_in_document(
            token,
            title_url,
            glued_forms=glues.get(token, ()),
        )
        for token in phrase
    )


def _requires_name_phrase(company_tokens: set[str]) -> bool:
    return bool(company_tokens) and not any(
        _is_distinctive_token(token) for token in company_tokens
    )


def _hyphen_tail_tokens(company: str) -> set[str]:
    parts = _HYPHEN_SPLIT_PATTERN.split(company, maxsplit=1)
    if len(parts) < 2:
        return set()
    return set(_tokenize(parts[1]))


def _optional_company_tokens(company: str, company_tokens: set[str]) -> set[str]:
    """Address tokens after a hyphen (Asoke Sukhumvit 15) may be absent on an
    official brand page. A soi number is optional only when a distinctive brand
    token already appears in the title or URL, so Centre Point 10 cannot match
    Grande Centre Point 55."""
    optional = _hyphen_tail_tokens(company) & company_tokens
    return optional


def _distinctive_in_title_or_url(
    company_tokens: set[str],
    document: SearchDocument,
    glues: dict[str, tuple[str, ...]],
) -> bool:
    title_url = _title_url_document(document)
    return any(
        _is_distinctive_token(token)
        and _token_appears_in_document(
            token,
            title_url,
            glued_forms=glues.get(token, ()),
        )
        for token in company_tokens
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


def _should_glue_adjacent(left: str, right: str) -> bool:
    """Glue only when a neighbor is short, numeric, or a dropped function word.
    That lets `nut` match URL `onnut` without treating every name pair as one slug."""
    return (
        len(left) < 4
        or len(right) < 4
        or left.isdigit()
        or right.isdigit()
        or left in _FUNCTION_WORDS
        or right in _FUNCTION_WORDS
    )


def _neighbor_glues(company: str) -> dict[str, tuple[str, ...]]:
    tokens = _strip_parent_segment(_tokenize(company))
    glues: dict[str, list[str]] = {}
    for index, token in enumerate(tokens):
        forms: list[str] = []
        if index > 0 and _should_glue_adjacent(tokens[index - 1], token):
            forms.append(tokens[index - 1] + token)
        if index + 1 < len(tokens) and _should_glue_adjacent(token, tokens[index + 1]):
            forms.append(token + tokens[index + 1])
        if forms:
            glues[token] = tuple(dict.fromkeys(forms))
    return glues


def _glued_form_appears(glued: str, document: SearchDocument) -> bool:
    if glued in _document_tokens(document):
        return True
    return any(glued in run for run in _document_url_runs(document))


def _token_appears_in_document(
    token: str,
    document: SearchDocument,
    *,
    glued_forms: tuple[str, ...] = (),
) -> bool:
    """A brand token glued into a hostname (`movenpickbangkoksukhumvit15`) still counts.
    Substring matching is URL-only, so title words like `teambuilding` do not satisfy
    `building`. Short tokens and bare numbers never substring-match, except when an
    adjacent name token concatenates to a form that does appear (`on`+`nut` → `onnut`)."""
    tokens = _document_tokens(document)
    if token in tokens:
        return True
    if any(_glued_form_appears(glued, document) for glued in glued_forms):
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
    glues = _neighbor_glues(company)
    missing = {
        token
        for token in company_tokens
        if not _token_appears_in_document(
            token,
            document,
            glued_forms=glues.get(token, ()),
        )
    }
    if missing:
        optional = _optional_company_tokens(company, company_tokens)
        hard_missing = missing - optional
        if hard_missing:
            if any(not token.isdigit() for token in hard_missing):
                return False
            if not _distinctive_in_title_or_url(company_tokens, document, glues):
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
    glues = _neighbor_glues(company)
    missing = sorted(
        token
        for token in company_tokens
        if not _token_appears_in_document(
            token,
            document,
            glued_forms=glues.get(token, ()),
        )
    )
    if missing:
        return missing
    if _requires_name_phrase(company_tokens) and not _name_phrase_appears(company, document):
        return [" ".join(_company_name_phrase(company))]
    return []


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


def _format_does_not_count(items: list[str] | None) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def extract_evidence_from_search_batch(
    *,
    company: str,
    requirement: str,
    search_query: str,
    search_focus: str,
    prior_verified_claims: list[str],
    batch_documents: dict[str, SearchDocument],
    positive_when: str = "",
    negative_when: str = "",
    does_not_count: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> tuple[list[Evidence], int]:
    if not batch_documents:
        return [], 0

    human_message = (
        f"Company: {company}\n"
        f"Search focus for this batch: {search_focus}\n\n"
        f"Met when: {positive_when}\n"
        f"Not met when: {negative_when}\n"
        f"Does not count:\n{_format_does_not_count(does_not_count)}\n\n"
        f"Already verified claims (do not re-extract):\n"
        f"{_format_verified_claims(prior_verified_claims)}\n\n"
        f"Search results from this search only:\n"
        f"{_format_batch_results(batch_documents)}"
    )

    result = structured_search_batch_evidence_llm.invoke([
        SystemMessage(
            content=with_domain_rules(
                SEARCH_BATCH_EVIDENCE_PROMPT,
                skill_ids,
                "extract",
            )
        ),
        HumanMessage(content=human_message),
    ])

    resolved: list[Evidence] = []
    result_id_match_failures = 0
    for item in result.evidence:
        matched = _resolve_evidence_to_batch(item, batch_documents)
        if matched is not None:
            resolved.append(matched)
        else:
            result_id_match_failures += 1
    return resolved, result_id_match_failures
