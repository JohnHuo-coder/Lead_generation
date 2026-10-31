from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_verification_llm
from prompts.system_prompts import VERIFICATION_SYSTEM_PROMPT
from schemas.research_schemas import (
    Evidence,
    SearchDocument,
    UnclearOwnershipJudgment,
    VerifierJudgment,
    VerifyResult,
)
from services.tavily_extract import extract_page_content


def _normalize_for_match(text: str) -> str:
    return " ".join(text.split()).casefold()


def _judgment(
    evidence: Evidence,
    *,
    title: str,
    url: str,
    source_content: str,
    result: VerifyResult,
) -> VerifierJudgment:
    return VerifierJudgment(
        claim=evidence.claim,
        title=title,
        url=url,
        source_content=source_content,
        about_this_company=result.about_this_company,
        support=result.support,
        reason=result.reason,
        supporting_passages=result.supporting_passages if result.support else [],
    )


def _unclear_ownership(
    evidence: Evidence,
    *,
    title: str,
    url: str,
    snippet: str,
) -> UnclearOwnershipJudgment:
    return UnclearOwnershipJudgment(
        claim=evidence.claim,
        title=title,
        url=url,
        snippet=snippet,
    )


def _build_check_failure(
    evidence: Evidence,
    *,
    check_stage: str,
    failure_reason: str,
    verification_reason: str = "",
    source_content: str = "",
    pipeline_stats: dict[str, int] | None = None,
    verifier_judgments: list[VerifierJudgment] | None = None,
    unclear_ownership_judgments: list[UnclearOwnershipJudgment] | None = None,
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
                "mismatched_excerpts": [],
                "verification_reason": verification_reason,
                "source_content": source_content,
            }
        ]
    }
    if verifier_judgments:
        payload["verifier_judgments"] = verifier_judgments
    if unclear_ownership_judgments:
        payload["unclear_ownership_judgments"] = unclear_ownership_judgments
    if pipeline_stats:
        payload.update(pipeline_stats)
    return payload


def _accepted(evidence: Evidence, passages: list[str]) -> Evidence:
    return evidence.model_copy(update={"supporting_passages": list(passages or [])})


def _run_claim_verification(
    *,
    company: str,
    claim: str,
    title: str,
    url: str,
    source_content: str,
    content_note: str = "",
) -> VerifyResult:
    note_block = f"\n\n{content_note}" if content_note else ""
    return structured_verification_llm.invoke([
        SystemMessage(content=VERIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Claim: {claim}\n"
            f"Source title: {title}\n"
            f"Source URL: {url}\n\n"
            f"Source text:\n{source_content}"
            f"{note_block}"
        )),
    ])


def _passed(result: VerifyResult) -> bool:
    return bool(result.about_this_company and result.support)


def verify_evidence_item(
    evidence: Evidence,
    *,
    company: str,
    search_documents: dict[str, SearchDocument],
) -> dict:
    document = search_documents.get(evidence.result_id)
    if not document:
        return _build_check_failure(
            evidence,
            check_stage="evidence_validation",
            failure_reason="invalid_result_id",
        )

    source_content = document["content"]
    title = document.get("title") or ""
    url = evidence.url or document.get("url") or ""
    is_full_page = bool(document.get("full_page"))
    source_type = (
        "full page content already extracted for this URL"
        if is_full_page
        else "Tavily search snippet"
    )
    first = _run_claim_verification(
        company=company,
        claim=evidence.claim,
        title=title,
        url=url,
        source_content=source_content,
        content_note=f"Source type: {source_type}.",
    )
    if _passed(first):
        return {
            "verified_evidence": [_accepted(evidence, first.supporting_passages)],
            "verifier_judgments": [
                _judgment(
                    evidence,
                    title=title,
                    url=url,
                    source_content=source_content,
                    result=first,
                )
            ],
        }

    if is_full_page or not first.unclear_ownership:
        failure_reason = (
            "not_about_company"
            if not first.about_this_company
            else "claim_not_supported"
        )
        return _build_check_failure(
            evidence,
            check_stage="claim_verification",
            failure_reason=failure_reason,
            verification_reason=first.reason,
            source_content=source_content,
            verifier_judgments=[
                _judgment(
                    evidence,
                    title=title,
                    url=url,
                    source_content=source_content,
                    result=first,
                )
            ],
        )

    unclear = [_unclear_ownership(evidence, title=title, url=url, snippet=source_content)]
    pipeline_stats = {"evidence_full_page_extracts": 1}
    try:
        full_page_content = extract_page_content(url)
    except RuntimeError as exc:
        return _build_check_failure(
            evidence,
            check_stage="claim_verification",
            failure_reason="page_extract_failed",
            verification_reason=str(exc),
            source_content=source_content,
            pipeline_stats=pipeline_stats,
            unclear_ownership_judgments=unclear,
        )

    retry = _run_claim_verification(
        company=company,
        claim=evidence.claim,
        title=title,
        url=url,
        source_content=full_page_content,
        content_note=(
            "Source type: full page content extracted with Tavily Extract because "
            "ownership was unclear in the shorter search snippet."
        ),
    )
    final_judgment = _judgment(
        evidence,
        title=title,
        url=url,
        source_content=full_page_content,
        result=retry,
    )
    if _passed(retry):
        return {
            "verified_evidence": [_accepted(evidence, retry.supporting_passages)],
            "verifier_judgments": [final_judgment],
            "unclear_ownership_judgments": unclear,
            **pipeline_stats,
        }

    failure_reason = (
        "not_about_company"
        if not retry.about_this_company
        else "claim_not_supported"
    )
    return _build_check_failure(
        evidence,
        check_stage="claim_verification",
        failure_reason=failure_reason,
        verification_reason=retry.reason,
        source_content=full_page_content,
        pipeline_stats=pipeline_stats,
        verifier_judgments=[final_judgment],
        unclear_ownership_judgments=unclear,
    )


def _claim_key(claim: str) -> str:
    return _normalize_for_match(claim)


def merge_verification_updates(
    updates: list[dict],
    prior_verified_evidence: list[Evidence],
) -> tuple[dict, int]:
    merged: dict = {}
    seen_claims = {_claim_key(evidence.claim) for evidence in prior_verified_evidence}
    duplicate_claim_skips = 0
    for update in updates:
        verified = update.get("verified_evidence") or []
        for evidence in verified:
            key = _claim_key(evidence.claim)
            if key in seen_claims:
                duplicate_claim_skips += 1
                continue
            merged.setdefault("verified_evidence", []).append(evidence)
            seen_claims.add(key)

        failures = update.get("failed_evidence_checks") or []
        if failures:
            merged.setdefault("failed_evidence_checks", []).extend(failures)

        judgments = update.get("verifier_judgments") or []
        if judgments:
            merged.setdefault("verifier_judgments", []).extend(judgments)

        unclear = update.get("unclear_ownership_judgments") or []
        if unclear:
            merged.setdefault("unclear_ownership_judgments", []).extend(unclear)

        for key in ("evidence_full_page_extracts",):
            value = update.get(key)
            if value:
                merged[key] = merged.get(key, 0) + value
    return merged, duplicate_claim_skips
