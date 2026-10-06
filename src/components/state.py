from typing import Annotated, NotRequired, TypedDict
from operator import add, or_
from langchain.agents import AgentState

from schemas.research_schemas import (
    Evidence,
    EvidenceCheckFailure,
    OffTargetRejection,
    SearchDocument,
)
from schemas.test_research_schemas import (
    FailedEvidence,
    TestEvidence,
    TestSearchDocument,
    VerifierJudgment,
)

class OverallState(TypedDict):
    config_id: int
    place_id: str
    company: str
    requirement: str

    sufficient: bool | None
    sufficient_reason: str
    verified_evidence: Annotated[list[Evidence], add]

    fit_passed: bool
    fit_score: int
    fit_reason: str

    company_website: NotRequired[str]
    rfp_url: NotRequired[str | None]
    rfp_summary: NotRequired[str]
    fallback_email: NotRequired[str | None]



class ResearchAgentState(AgentState):
    tool_call_count: Annotated[int, add]
    search_documents: Annotated[dict[str, SearchDocument], or_]
    company: str
    requirement: str
    verified_evidence: Annotated[list[Evidence], add]
    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    batch_result_id_match_failures: Annotated[int, add]
    off_target_company_rejections: Annotated[int, add]
    off_target_rejections: Annotated[list[OffTargetRejection], add]
    duplicate_search_result_skips: Annotated[int, add]
    duplicate_claim_skips: Annotated[int, add]
    empty_evidence_tool_calls: Annotated[int, add]
    url_selector_extract_attempts: Annotated[int, add]
    url_selector_full_page_extracts: Annotated[int, add]
    url_selector_extract_failures: Annotated[int, add]
    search_queries_used: Annotated[list[str], add]
    excerpt_derivation_checks: Annotated[int, add]
    evidence_full_snippet_verifications: Annotated[int, add]
    evidence_full_page_extracts: Annotated[int, add]

class ResearchInput(TypedDict):
    company: str
    requirement: str

class ResearchOutput(TypedDict):
    sufficient: bool
    sufficient_reason: str
    verified_evidence: list[Evidence]

class ResearchState(TypedDict):
    company: str
    requirement: str
    additional_evidence_needed: NotRequired[list[str]]
    search_documents: Annotated[dict[str, SearchDocument], or_]

    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    verified_evidence: Annotated[list[Evidence], add]

    sufficient: bool | None
    sufficient_reason: str
    search_tool_call_count: int

    batch_result_id_match_failures: Annotated[int, add]
    off_target_company_rejections: Annotated[int, add]
    off_target_rejections: Annotated[list[OffTargetRejection], add]
    duplicate_search_result_skips: Annotated[int, add]
    duplicate_claim_skips: Annotated[int, add]
    empty_evidence_tool_calls: Annotated[int, add]
    url_selector_extract_attempts: Annotated[int, add]
    url_selector_full_page_extracts: Annotated[int, add]
    url_selector_extract_failures: Annotated[int, add]
    search_queries_used: Annotated[list[str], add]
    excerpt_derivation_checks: Annotated[int, add]
    evidence_full_snippet_verifications: Annotated[int, add]
    evidence_full_page_extracts: Annotated[int, add]


class TestResearchAgentState(AgentState):
    company: str
    requirement: str
    search_documents: Annotated[dict[str, TestSearchDocument], or_]
    inspected_urls: Annotated[dict[str, bool], or_]
    verified_evidence: Annotated[list[TestEvidence], add]
    failed_evidence: Annotated[list[FailedEvidence], add]
    verifier_judgments: Annotated[list[VerifierJudgment], add]
    search_queries_used: Annotated[list[str], add]
    web_search_count: Annotated[int, add]


class TestResearchInput(TypedDict):
    company: str
    requirement: str


class TestResearchOutput(TypedDict):
    sufficient: bool
    sufficient_reason: str
    verified_evidence: list[TestEvidence]
    failed_evidence: list[FailedEvidence]
    verifier_judgments: list[VerifierJudgment]
    search_tool_call_count: int
    inspect_tool_call_count: int
    write_evidence_tool_call_count: int
    think_tool_call_count: int


class TestResearchState(TypedDict):
    company: str
    requirement: str
    sufficient: bool | None
    sufficient_reason: str
    verified_evidence: Annotated[list[TestEvidence], add]
    failed_evidence: Annotated[list[FailedEvidence], add]
    verifier_judgments: Annotated[list[VerifierJudgment], add]
    search_documents: Annotated[dict[str, TestSearchDocument], or_]
    search_queries_used: Annotated[list[str], add]
    search_tool_call_count: int
    inspect_tool_call_count: int
    write_evidence_tool_call_count: int
    think_tool_call_count: int


class RfpAgentState(AgentState):
    fallback_email: NotRequired[str | None]


class RFPInput(TypedDict):
    company: str
    company_website: NotRequired[str]


class RFPUpdate(TypedDict, total=False):
    rfp_url: str | None
    rfp_summary: str
    fallback_email: str | None


class FitScoreInput(TypedDict):
    company: str
    requirement: str
    verified_evidence: list[Evidence]

class FitScoreUpdate(TypedDict):
    passed: bool
    fit_score: int
    reason: str