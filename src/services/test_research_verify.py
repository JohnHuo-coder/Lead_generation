from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_test_research_verify_llm
from prompts.test_research import TEST_RESEARCH_VERIFY_PROMPT
from schemas.test_research_schemas import (
    FailedEvidence,
    TestEvidence,
    TestSearchDocument,
    VerifierJudgment,
)

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


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _normalize_tokens_source(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokenize(text: str) -> list[str]:
    return _WORD_PATTERN.findall(_normalize_tokens_source(text))


def _strip_parent_segment(tokens: list[str]) -> list[str]:
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


def source_mentions_company(
    *,
    title: str,
    url: str,
    content: str,
    company: str,
) -> bool:
    company_tokens = _company_tokens(company)
    if not company_tokens:
        return False

    runs = _tokenize(" ".join([title, url, content]))
    url_runs = _tokenize(url)
    tokens: set[str] = set()
    for run in runs:
        tokens.add(run)
        tokens.update(_SUBWORD_PATTERN.findall(run))

    def token_appears(token: str) -> bool:
        if token in tokens:
            return True
        if token.isdigit() or len(token) < 4:
            return False
        return any(token in run for run in url_runs)

    if not all(token_appears(token) for token in company_tokens):
        return False

    if not any(_is_distinctive_token(token) for token in company_tokens):
        phrase = [
            token
            for token in _strip_parent_segment(_tokenize(company))
            if token not in _FUNCTION_WORDS
        ]
        width = len(phrase)
        if width and any(
            runs[index:index + width] == phrase
            for index in range(len(runs) - width + 1)
        ):
            return True
        glued = "".join(phrase)
        return any(glued in run for run in url_runs)
    return True


def _claim_key(claim: str) -> str:
    return _normalize_text(claim)

# after verification, return non-repeated new evidence
def merge_verified_evidence(
    new_items: list[TestEvidence],
    prior_verified: list[TestEvidence],
) -> list[TestEvidence]:
    seen = {_claim_key(item.claim) for item in prior_verified}
    merged: list[TestEvidence] = []
    for item in new_items:
        key = _claim_key(item.claim)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged

@dataclass
class VerifyOutcome:
    evidence: TestEvidence | None = None
    failed: FailedEvidence | None = None
    judgment: VerifierJudgment | None = None


def _failed(claim: str, result_id: str, url: str, reason: str) -> FailedEvidence:
    return FailedEvidence(
        claim=claim,
        result_id=result_id,
        url=url,
        reason=reason,
    )


# check result_id exists, source is about the target company,
# claim is about the target company, and the source text supports the claim
def verify_three_steps(
    *,
    claim: str,
    result_id: str,
    company: str,
    search_documents: dict[str, TestSearchDocument],
) -> VerifyOutcome:
    document = search_documents.get(result_id)
    if document is None:
        return VerifyOutcome(
            failed=_failed(
                claim, result_id, "", f"result_id {result_id} is not in search_documents"
            )
        )

    if not source_mentions_company(
        title=document["title"],
        url=document["url"],
        content=document["content"],
        company=company,
    ):
        return VerifyOutcome(
            failed=_failed(
                claim,
                result_id,
                document["url"],
                "the source does not refer to the target company",
            )
        )

    result = structured_test_research_verify_llm.invoke([
        SystemMessage(content=TEST_RESEARCH_VERIFY_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Claim: {claim}\n\n"
            f"Source text:\n{document['content']}"
        )),
    ])
    judgment = VerifierJudgment(
        claim=claim,
        source_content=document["content"],
        support=result.support,
        reason=result.reason,
        supporting_passages=result.supporting_passages if result.support else [],
    )
    if not result.about_this_company:
        reason = f"the claim is not about the target company: {result.reason}"
        return VerifyOutcome(
            failed=_failed(claim, result_id, document["url"], reason),
            judgment=judgment,
        )
    if not result.support:
        reason = f"source does not support the claim: {result.reason}"
        return VerifyOutcome(
            failed=_failed(claim, result_id, document["url"], reason),
            judgment=judgment,
        )

    return VerifyOutcome(
        evidence=TestEvidence(
            claim=claim,
            result_id=result_id,
            url=document["url"],
            supporting_passages=result.supporting_passages,
        ),
        judgment=judgment,
    )
