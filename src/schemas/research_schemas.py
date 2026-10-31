from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, model_validator


class ResearchRequirement(BaseModel):
    id: str = Field(
        description="Short snake_case label, e.g. meeting_space, group_catering, on_site_amenities."
    )
    description: str = Field(
        description="What this requirement covers, in one or two sentences."
    )
    positive_when: str = Field(
        description=(
            "Pass condition verified claims must jointly establish. Write the "
            "business fact (thresholds, on-site vs nearby). Do not name page "
            "types, required wording, or kitchen/staffing details unless the "
            "user asked."
        )
    )
    negative_when: str = Field(
        description=(
            "Fail condition verified claims must jointly establish. Same "
            "rules as positive_when: a judgment condition, not a search recipe."
        )
    )
    does_not_count: list[str] = Field(
        default_factory=list,
        description=(
            "Statements that must not satisfy or refute this requirement. "
            "Exclusions only (nearby venues, sibling properties, house rules). "
            "Do not list values that fail a numeric threshold; those belong "
            "in negative_when."
        ),
    )
    skills: list[str] = Field(
        default_factory=list,
        description=(
            "Domain skill ids to attach for later research. Choose only from "
            "the available catalog. Empty if none apply."
        ),
    )


class DomainSkillChoice(BaseModel):
    skills: list[str] = Field(
        default_factory=list,
        description="Domain skill ids to attach. Empty if none apply.",
    )


class ResearchPlan(BaseModel):
    requirements: list[ResearchRequirement] = Field(
        description="Requirements grouped by the pages that usually answer them."
    )


class SearchDocument(TypedDict):
    query: str
    search_focus: str
    title: str
    url: str
    content: str
    full_page: NotRequired[bool]


class OffTargetRejection(TypedDict):
    """A search result dropped because it never mentions the target company."""

    query: str
    search_focus: str
    title: str
    url: str
    missing_tokens: list[str]


class PipelineStats(TypedDict):
    batch_result_id_match_failures: int
    off_target_company_rejections: int
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
        "not_about_company",
        "claim_not_supported",
    ]
    mismatched_excerpts: list[str]
    verification_reason: str
    source_content: str


class VerifierJudgment(BaseModel):
    claim: str
    title: str
    url: str
    source_content: str
    about_this_company: bool
    support: bool
    reason: str
    supporting_passages: list[str] = Field(default_factory=list)


class UnclearOwnershipJudgment(BaseModel):
    claim: str
    title: str
    url: str
    snippet: str


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
    supporting_passages: list[str] = Field(
        default_factory=list,
        description=(
            "Source passages copied by the verifier when the claim is accepted. "
            "Empty until verification succeeds."
        ),
    )
    reason: str = Field(description="Why this claim is relevant to the requirement.")


class SearchBatchEvidenceResult(BaseModel):
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence extracted from the current search batch only.",
    )


class UrlSelectorChoice(BaseModel):
    url: str = Field(
        description="Exact URL from the provided search results to fetch in full."
    )
    reason: str = Field(
        description="Why this page is likely to contain detailed evidence for search_focus."
    )


class UrlSelectorResult(BaseModel):
    selections: list[UrlSelectorChoice] = Field(
        default_factory=list,
        max_length=2,
        description="One or two URLs whose full page content should be extracted.",
    )


class UrlSelectorPage(BaseModel):
    title: str
    url: str
    content: str


# company and requirement are omitted here; add them later uniformly for eval.
class UrlSelectorDecision(BaseModel):
    search_focus: str
    search_query: str
    candidates: list[UrlSelectorPage] = Field(default_factory=list)
    selections: list[UrlSelectorChoice] = Field(default_factory=list)


# company and requirement are omitted here; add them later uniformly for eval.
# Full decision list is eval'd together: prior queries are earlier steps' query.
class QueryGeneratorDecision(BaseModel):
    search_focus: str
    prior_verified_claims: list[str] = Field(default_factory=list)
    prior_source_urls: list[str] = Field(default_factory=list)
    query: str


class ExtractorDocument(BaseModel):
    result_id: str
    title: str
    url: str
    content: str
    full_page: bool = False


class ExtractorClaim(BaseModel):
    claim: str
    result_id: str
    source_excerpts: list[str] = Field(default_factory=list)


# company and requirement are omitted here; add them later uniformly for eval.
class EvidenceExtractorDecision(BaseModel):
    search_focus: str
    search_query: str
    requirement_id: str = ""
    prior_verified_claims: list[str] = Field(default_factory=list)
    documents: list[ExtractorDocument] = Field(default_factory=list)
    extracted: list[ExtractorClaim] = Field(default_factory=list)


# company and requirement are omitted here; add them later uniformly for eval.
# Full step list is eval'd together: prior evidence is the prefix of evidence_received.
class ResearchAgentStep(BaseModel):
    search_focus: str
    evidence_received: list[str] = Field(default_factory=list)


class QueryGeneratorResult(BaseModel):
    query: str = Field(
        description="Keyword query for Tavily web search, typically 4-12 words."
    )
    rationale: str = Field(
        description="Brief explanation of why this query angle fits search_focus."
    )


class ResearchResult(BaseModel):
    sufficient: bool = Field(
        description=(
            "Whether the collected evidence is enough to evaluate the requirement, "
            "not whether the company meets it. This is the final research decision "
            "after search is complete."
        )
    )
    satisfied: bool | None = Field(
        description=(
            "If sufficient=true: true when the verified claims show the company "
            "meets the requirement (POSITIVE path), false when they show it does "
            "not (NEGATIVE path). If sufficient=false: must be null."
        )
    )
    additional_evidence_needed: list[str] = Field(
        description=(
            "Only facts that are still absent from the verified claims and that "
            "block evaluating the requirement. Each item must be one required fact "
            "named in the requirement that verified claims never established. "
            "Do not list a fact already established by verified claims. "
            "Do not request more detail or a different source to reconfirm an established "
            "fact. Empty list when sufficient=true. "
        ),
        max_length=5,
    )
    reason: str = Field(
        default="",
        description=(
            "If sufficient=true, why the claims show the company meets or does "
            "not meet the requirement. If sufficient=false, why the evidence "
            "is not enough to evaluate."
        ),
    )

    @model_validator(mode="after")
    def _align_satisfied(self) -> "ResearchResult":
        if not self.sufficient:
            self.satisfied = None
        elif self.satisfied is None:
            raise ValueError("satisfied is required when sufficient=true")
        return self

class VerifyResult(BaseModel):
    about_this_company: bool = Field(
        description=(
            "Whether the claim and source are about the target company, including "
            "an official name, brand name, or common alias. False for a sibling "
            "property, nearby business, or generic listing."
        )
    )
    support: bool = Field(
        description="Whether the provided source text supports the claim."
    )
    supporting_passages: list[str] = Field(
        default_factory=list,
        description=(
            "If support=true, copy the source passages that support the claim. "
            "Empty when support=false."
        ),
    )
    reason: str = Field(
        description="A concise explanation citing the relevant source text."
    )
    unclear_ownership: bool = Field(
        default=False,
        description=(
            "When support=false, true only if the source mentions a relevant "
            "service or facility but does not make clear whether it belongs to "
            "the target company versus a nearby business, partner, or third party."
        ),
    )

    @model_validator(mode="after")
    def _align_fields(self) -> "VerifyResult":
        if self.support:
            self.unclear_ownership = False
            if not self.about_this_company:
                self.support = False
        if not self.support:
            self.supporting_passages = []
        return self
