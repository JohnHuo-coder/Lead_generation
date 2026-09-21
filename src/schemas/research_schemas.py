from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class SearchDocument(TypedDict):
    query: str
    search_focus: str
    title: str
    url: str
    content: str


class PipelineStats(TypedDict):
    batch_result_id_match_failures: int
    off_target_company_rejections: int
    excerpt_derivation_checks: int
    evidence_full_snippet_verifications: int
    evidence_full_page_extracts: int


class EvidenceCheckFailure(TypedDict):
    claim: str
    result_id: str
    url: str
    source_excerpts: list[str]
    reason: str
    check_stage: Literal[
        "evidence_validation",
        "snippet_excerpt",
        "full_page_excerpt",
        "claim_verification",
    ]
    failure_reason: Literal[
        "invalid_result_id",
        "excerpt_not_found",
        "missing_excerpts",
        "page_extract_failed",
        "claim_not_supported",
    ]
    mismatched_excerpts: list[str]
    verification_reason: str
    source_content: str


class Evidence(BaseModel):
    claim: str = Field(description="A factual claim supported by the source.")
    result_id: str = Field(
        description=(
            "The result_id of the specific search result whose content was used to derive "
            "this claim."
        )
    )
    url: str = Field(description="The URL of the search result supporting this claim.")
    source_excerpts: list[str] = Field(
        min_length=1,
        max_length=5,
        description=(
            "1 to 5 exact short excerpts copied character-for-character from the content field "
            "of the search result identified by result_id. Each excerpt must directly support "
            "the claim. Do not paraphrase, summarize, or compute values (e.g. do not derive "
            "area from dimensions unless that exact computed value appears in the content)."
        ),
    )
    reason: str = Field(description="Why this claim is relevant to the requirement.")


class SearchBatchEvidenceResult(BaseModel):
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence extracted from the current search batch only.",
    )


class ResearchResult(BaseModel):
    sufficient: bool = Field(
        description=(
            "Whether the collected evidence is enough to evaluate the requirement, "
            "not whether the company meets it. This is the final research decision "
            "after search is complete."
        )
    )
    additional_evidence_needed: list[str] = Field(
        description=(
            "Specific information still missing from the collected evidence; "
            "return an empty list when sufficient=true. Do not put search queries here."
        )
    )
    reason: str = Field(
        default="",
        description=(
            "When sufficient=true, briefly explain which verified claims cover the "
            "requirement and why that is enough to evaluate it. Cite the key facts, "
            "not whether the company qualifies. Return an empty string when sufficient=false."
        ),
    )

class ExcerptDerivationResult(BaseModel):
    derived_from_content: bool = Field(
        description=(
            "True when the excerpt is a faithful restatement of content already present, "
            "or a direct calculation from numbers explicitly stated in the content."
        )
    )
    reason: str = Field(
        description="Concise explanation citing the relevant content or what is missing."
    )


class VerifyResult(BaseModel):
    support: bool = Field(description="Whether the source excerpts support the claim.")
    reason: str = Field(
        description="A concise explanation citing the relevant excerpt content."
    )
    unclear_ownership: bool = Field(
        default=False,
        description=(
            "When support=false, set to true only if the main issue is that the excerpts "
            "mention a service or facility but do not clearly indicate whether it belongs "
            "to the target company versus a nearby business, partner, or third party."
        ),
    )
