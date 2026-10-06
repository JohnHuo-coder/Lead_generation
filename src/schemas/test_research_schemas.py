from typing import TypedDict

from pydantic import BaseModel, Field


class TestSearchDocument(TypedDict):
    title: str
    url: str
    content: str


class CandidateEvidence(BaseModel):
    evidence: str = Field(description="One factual claim sentence about the target company.")
    result_id: str = Field(
        description="The result_id from a previous web_search result that supports this claim."
    )


class TestEvidence(BaseModel):
    claim: str
    result_id: str
    url: str
    supporting_passages: list[str] = Field(default_factory=list)


class FailedEvidence(BaseModel):
    claim: str
    result_id: str
    url: str
    reason: str


class VerifierJudgment(BaseModel):
    claim: str
    source_content: str
    support: bool
    reason: str
    supporting_passages: list[str] = Field(default_factory=list)


class PageEvidenceItem(BaseModel):
    claim: str = Field(description="A factual claim about the target company.")

# extracted evidence from inspect_web_page
class PageEvidenceResult(BaseModel):
    evidence: list[PageEvidenceItem] = Field(default_factory=list)


class TestVerifyResult(BaseModel):
    about_this_company: bool = Field(
        description="Whether the claim is about the target company, not a sibling or nearby business."
    )
    support: bool = Field(description="Whether the source text supports the claim.")
    supporting_passages: list[str] = Field(
        default_factory=list,
        description=(
            "If support=true, the source passages that support the claim, "
            "copied from the provided text for later human review. "
            "Empty when support=false."
        ),
    )
    reason: str


class TestResearchResult(BaseModel):
    sufficient: bool = Field(
        description=(
            "Whether the collected evidence is enough to evaluate the requirement, "
            "not whether the company meets it."
        )
    )
    additional_evidence_needed: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Required facts still missing from verified claims. Empty when sufficient=true.",
    )
    reason: str = Field(description="Why the evidence is or is not enough to evaluate the requirement.")






class ToolAction(BaseModel):
    name: str
    arguments: dict



class AgentDecisionExample(BaseModel):
    requirement: str
    verified_evidence_before: list[TestEvidence]
    current_search_focus: str

    previous_action: ToolAction | None
    last_web_search_results: list[TestSearchDocument]
    looked_back_search_results: list[TestSearchDocument] | None

    latest_reflection: str | None

    seen_queries: list[str]
    inspected_urls: list[str]

    chosen_action: ToolAction