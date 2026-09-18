from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from llm.models import structured_excerpt_derivation_llm, structured_verification_llm
from prompts.system_prompts import (
    EXCERPT_DERIVATION_SYSTEM_PROMPT,
    VERIFICATION_SYSTEM_PROMPT,
)
from schemas.research_schemas import Evidence, ExcerptDerivationResult, SearchDocument, VerifyResult
from services.tavily_extract import extract_page_content

SEARCH_SNIPPET_CONTEXT_CHARS = 300
FULL_PAGE_CONTEXT_CHARS = 1000


class DerivationCheck(TypedDict):
    excerpt: str
    derived_from_content: bool
    reason: str


class ExcerptResolutionResult(TypedDict):
    verbatim: list[str]
    derived: list[str]
    rejected: list[str]
    derivation_checks: list[DerivationCheck]


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _normalize_for_match(text: str) -> str:
    return _normalize_text(text).casefold()


def _excerpt_in_content(excerpt: str, content: str) -> bool:
    normalized_excerpt = _normalize_for_match(excerpt)
    if not normalized_excerpt:
        return False
    return normalized_excerpt in _normalize_for_match(content)


def _partition_excerpts(
    content: str,
    excerpts: list[str],
) -> tuple[list[str], list[str]]:
    verbatim: list[str] = []
    non_verbatim: list[str] = []
    for excerpt in excerpts:
        if _excerpt_in_content(excerpt, content):
            verbatim.append(excerpt)
        else:
            non_verbatim.append(excerpt)
    return verbatim, non_verbatim


@traceable(name="check_excerpt_derivation", run_type="llm")
def _check_excerpt_derivation(content: str, excerpt: str) -> ExcerptDerivationResult:
    return structured_excerpt_derivation_llm.invoke([
        SystemMessage(content=EXCERPT_DERIVATION_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Source content:\n{content}\n\n"
            f"Candidate excerpt:\n{excerpt}"
        )),
    ])


@traceable(name="resolve_excerpts_against_content", run_type="chain")
def _resolve_excerpts_against_content(
    content: str,
    excerpts: list[str],
) -> ExcerptResolutionResult:
    verbatim, non_verbatim = _partition_excerpts(content, excerpts)
    derived: list[str] = []
    rejected: list[str] = []
    derivation_checks: list[DerivationCheck] = []
    for excerpt in non_verbatim:
        result = _check_excerpt_derivation(content, excerpt)
        derivation_checks.append({
            "excerpt": excerpt,
            "derived_from_content": result.derived_from_content,
            "reason": result.reason,
        })
        if result.derived_from_content:
            derived.append(excerpt)
        else:
            rejected.append(excerpt)
    return {
        "verbatim": verbatim,
        "derived": derived,
        "rejected": rejected,
        "derivation_checks": derivation_checks,
    }


def _build_check_failure(
    evidence: Evidence,
    *,
    check_stage: str,
    failure_reason: str,
    mismatched_excerpts: list[str] | None = None,
    verification_reason: str = "",
    source_content: str = "",
    pipeline_stats: dict[str, int] | None = None,
) -> dict:
    payload = {
        "failed_evidence_checks": [
            {
                "claim": evidence.claim,
                "result_id": evidence.result_id,
                "url": evidence.url,
                "source_excerpts": evidence.source_excerpts,
                "reason": evidence.reason,
                "check_stage": check_stage,
                "failure_reason": failure_reason,
                "mismatched_excerpts": mismatched_excerpts or [],
                "verification_reason": verification_reason,
                "source_content": source_content,
            }
        ]
    }
    if pipeline_stats:
        payload.update(pipeline_stats)
    return payload


def _build_pipeline_stats(
    *,
    excerpt_derivation_checks: int = 0,
    evidence_full_snippet_verifications: int = 0,
    evidence_full_page_extracts: int = 0,
) -> dict[str, int]:
    stats: dict[str, int] = {}
    if excerpt_derivation_checks:
        stats["excerpt_derivation_checks"] = excerpt_derivation_checks
    if evidence_full_snippet_verifications:
        stats["evidence_full_snippet_verifications"] = evidence_full_snippet_verifications
    if evidence_full_page_extracts:
        stats["evidence_full_page_extracts"] = evidence_full_page_extracts
    return stats


def _extract_context(
    content: str,
    excerpt: str,
    context_chars: int = SEARCH_SNIPPET_CONTEXT_CHARS,
) -> str | None:
    normalized_content = _normalize_text(content)
    normalized_excerpt = _normalize_text(excerpt)
    if not normalized_excerpt:
        return None

    start = normalized_content.casefold().find(normalized_excerpt.casefold())
    if start == -1:
        return None

    end = start + len(normalized_excerpt)
    left = max(0, start - context_chars)
    right = min(len(normalized_content), end + context_chars)
    return normalized_content[left:right]


def _collect_extended_excerpts(
    source_content: str,
    excerpts: list[str],
    *,
    context_chars: int,
) -> list[str]:
    return [
        _extract_context(source_content, excerpt, context_chars=context_chars)
        for excerpt in excerpts
    ]


def _format_extended_excerpts(extended_excerpts: list[str]) -> str:
    return "\n\n---\n\n".join(
        f"Excerpt {index + 1}:\n{context}"
        for index, context in enumerate(extended_excerpts)
    )


def _run_claim_verification(
    *,
    company: str,
    claim: str,
    formatted_excerpts: str = "",
    source_content: str = "",
    content_note: str = "",
) -> VerifyResult:
    note_block = f"\n\n{content_note}" if content_note else ""
    if source_content:
        source_block = f"Source content:\n{source_content}"
    else:
        source_block = f"Supporting source excerpts with context:\n{formatted_excerpts}"
    return structured_verification_llm.invoke([
        SystemMessage(content=VERIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Claim: {claim}\n\n"
            f"{source_block}"
            f"{note_block}"
        )),
    ])


def _resolve_verification_content(
    *,
    source_content: str,
    excerpts: list[str],
    derived_excerpts: list[str],
    context_chars: int,
) -> tuple[str, bool]:
    if derived_excerpts:
        return source_content, True

    extended_excerpts = _collect_extended_excerpts(
        source_content,
        excerpts,
        context_chars=context_chars,
    )
    return _format_extended_excerpts(extended_excerpts), False


def _expand_content_in_page(
    page_content: str,
    anchor_content: str,
    *,
    context_chars: int,
) -> str:
    expanded = _extract_context(
        page_content,
        anchor_content,
        context_chars=context_chars,
    )
    return expanded if expanded is not None else page_content


def verify_evidence_item(
    evidence: Evidence,
    *,
    company: str,
    search_documents: dict[str, SearchDocument],
) -> dict:
    result_id = evidence.result_id
    excerpts = evidence.source_excerpts

    if not excerpts:
        return _build_check_failure(
            evidence,
            check_stage="evidence_validation",
            failure_reason="missing_excerpts",
        )

    document = search_documents.get(result_id)
    if not document:
        return _build_check_failure(
            evidence,
            check_stage="evidence_validation",
            failure_reason="invalid_result_id",
            mismatched_excerpts=list(excerpts),
        )

    source_content = document["content"]
    excerpt_resolution = _resolve_excerpts_against_content(
        source_content,
        excerpts,
    )
    derived_excerpts = excerpt_resolution["derived"]
    rejected_excerpts = excerpt_resolution["rejected"]
    pipeline_stats = _build_pipeline_stats(
        excerpt_derivation_checks=len(excerpt_resolution["derivation_checks"]),
    )
    if rejected_excerpts:
        return _build_check_failure(
            evidence,
            check_stage="snippet_excerpt",
            failure_reason="excerpt_not_found",
            mismatched_excerpts=rejected_excerpts,
            source_content=source_content,
            pipeline_stats=pipeline_stats,
        )

    verification_input, use_full_content = _resolve_verification_content(
        source_content=source_content,
        excerpts=excerpts,
        derived_excerpts=derived_excerpts,
        context_chars=SEARCH_SNIPPET_CONTEXT_CHARS,
    )
    if use_full_content:
        pipeline_stats.update(
            _build_pipeline_stats(evidence_full_snippet_verifications=1)
        )
    derived_note = (
        " One or more excerpts were inferred rather than quoted verbatim; "
        "the full search snippet content is provided instead."
        if derived_excerpts
        else ""
    )
    verification_result = _run_claim_verification(
        company=company,
        claim=evidence.claim,
        formatted_excerpts=verification_input if not use_full_content else "",
        source_content=verification_input if use_full_content else "",
        content_note=f"Source type: Tavily search snippet content.{derived_note}",
    )

    if verification_result.support:
        return {"verified_evidence": [evidence], **pipeline_stats}

    if not verification_result.unclear_ownership:
        return _build_check_failure(
            evidence,
            check_stage="claim_verification",
            failure_reason="claim_not_supported",
            verification_reason=verification_result.reason,
            source_content=source_content,
            pipeline_stats=pipeline_stats,
        )

    pipeline_stats.update(_build_pipeline_stats(evidence_full_page_extracts=1))

    try:
        full_page_content = extract_page_content(evidence.url)
    except RuntimeError as exc:
        return _build_check_failure(
            evidence,
            check_stage="claim_verification",
            failure_reason="page_extract_failed",
            verification_reason=str(exc),
            source_content=source_content,
            pipeline_stats=pipeline_stats,
        )

    expanded_page_content = _expand_content_in_page(
        full_page_content,
        source_content,
        context_chars=FULL_PAGE_CONTEXT_CHARS,
    )

    retry_result = _run_claim_verification(
        company=company,
        claim=evidence.claim,
        source_content=expanded_page_content,
        content_note=(
            "Source type: full page content extracted with Tavily Extract because "
            "ownership was unclear in the shorter search snippet. "
            "The provided text is an expanded window around the original search snippet "
            "within the full page."
        ),
    )

    if retry_result.support:
        return {"verified_evidence": [evidence], **pipeline_stats}

    return _build_check_failure(
        evidence,
        check_stage="claim_verification",
        failure_reason="claim_not_supported",
        verification_reason=retry_result.reason,
        source_content=full_page_content,
        pipeline_stats=pipeline_stats,
    )


def merge_verification_updates(updates: list[dict]) -> dict:
    merged: dict = {}
    for update in updates:
        verified = update.get("verified_evidence") or []
        if verified:
            merged.setdefault("verified_evidence", []).extend(verified)

        failures = update.get("failed_evidence_checks") or []
        if failures:
            merged.setdefault("failed_evidence_checks", []).extend(failures)

        for key in (
            "excerpt_derivation_checks",
            "evidence_full_snippet_verifications",
            "evidence_full_page_extracts",
        ):
            value = update.get(key)
            if value:
                merged[key] = merged.get(key, 0) + value
    return merged
