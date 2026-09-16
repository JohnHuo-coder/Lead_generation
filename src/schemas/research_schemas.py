from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class SearchDocument(TypedDict):
    query: str
    title: str
    url: str
    content: str


class EvidenceCheckFailure(TypedDict):
    claim: str
    result_id: str
    url: str
    source_excerpts: list[str]
    reason: str
    check_stage: Literal["source_excerpt", "claim_verification"]
    failure_reason: Literal[
        "invalid_result_id",
        "excerpt_not_found",
        "missing_excerpts",
        "context_extraction_failed",
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
            "1 to 5 exact short excerpts copied verbatim from the content field of the search "
            "result identified by result_id. Each excerpt must directly support the claim. "
            "Do not paraphrase or quote from outside that result's content."
        ),
    )
    reason: str = Field(description="Why this claim is relevant to the requirement.")


class ResearchResult(BaseModel):
    evidence: list[Evidence] = Field(
        description="Relevant evidence; empty if none was found."
    )
    sufficient: bool = Field(
        description="Whether the collected evidence is enough to evaluate the requirement, not whether the company meets it."
    )
    additional_evidence_needed: list[str] = Field(
        description="Specific information still missing; empty when sufficient."
    )

class VerifyResult(BaseModel):
    support: bool = Field(description="Whether the source excerpts supports the claim")
    reason: str = Field(description="Reason behind the decision, why the source excerpt supports or not support the claim")
