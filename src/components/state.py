from typing import Annotated, NotRequired, TypedDict
from operator import add, or_
from langchain.agents import AgentState

from schemas.research_schemas import (
    Evidence,
    EvidenceCheckFailure,
    EvidenceExtractorDecision,
    OffTargetRejection,
    QueryGeneratorDecision,
    ResearchAgentStep,
    ResearchPlan,
    SearchDocument,
    UnclearOwnershipJudgment,
    UrlSelectorDecision,
    VerifierJudgment,
)

class OverallState(TypedDict):
    config_id: int
    place_id: str
    company: str
    requirement: str
    positive_when: str
    negative_when: str
    does_not_count: list[str]
    skills: list[str]

    sufficient: bool | None
    sufficient_reason: str
    verified_evidence: Annotated[list[Evidence], add]
    verified_claims: list[str]
    satisfied: bool | None

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
    positive_when: str
    negative_when: str
    does_not_count: list[str]
    skills: list[str]
    verified_evidence: Annotated[list[Evidence], add]
    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    verifier_judgments: Annotated[list[VerifierJudgment], add]
    unclear_ownership_judgments: Annotated[list[UnclearOwnershipJudgment], add]
    batch_result_id_match_failures: Annotated[int, add]
    off_target_company_rejections: Annotated[int, add]
    off_target_rejections: Annotated[list[OffTargetRejection], add]
    duplicate_search_result_skips: Annotated[int, add]
    duplicate_claim_skips: Annotated[int, add]
    empty_evidence_tool_calls: Annotated[int, add]
    url_selector_extract_attempts: Annotated[int, add]
    url_selector_full_page_extracts: Annotated[int, add]
    url_selector_extract_failures: Annotated[int, add]
    url_selector_decisions: Annotated[list[UrlSelectorDecision], add]
    query_generator_decisions: Annotated[list[QueryGeneratorDecision], add]
    evidence_extractor_decisions: Annotated[list[EvidenceExtractorDecision], add]
    research_agent_steps: Annotated[list[ResearchAgentStep], add]
    search_queries_used: Annotated[list[str], add]
    evidence_full_page_extracts: Annotated[int, add]

class ResearchInput(TypedDict):
    company: str
    requirement: str
    positive_when: str
    negative_when: str
    does_not_count: list[str]
    skills: NotRequired[list[str]]

class ResearchOutput(TypedDict):
    company: str
    requirement: str
    positive_when: str
    negative_when: str
    does_not_count: list[str]
    skills: list[str]
    sufficient: bool
    satisfied: bool | None
    sufficient_reason: str
    additional_evidence_needed: list[str]
    verified_evidence: list[Evidence]
    verified_claims: list[str]
    failed_evidence_checks: list[EvidenceCheckFailure]
    verifier_judgments: list[VerifierJudgment]
    verifier_sample_supported: VerifierJudgment | None
    verifier_sample_wrong_company: VerifierJudgment | None
    verifier_sample_unsupported: VerifierJudgment | None
    unclear_ownership_judgments: list[UnclearOwnershipJudgment]
    url_selector_decisions: list[UrlSelectorDecision]
    query_generator_decisions: list[QueryGeneratorDecision]
    evidence_extractor_decisions: list[EvidenceExtractorDecision]
    research_agent_steps: list[ResearchAgentStep]
    search_tool_call_count: int
    search_documents: dict[str, SearchDocument]
    search_queries_used: list[str]
    batch_result_id_match_failures: int
    off_target_company_rejections: int
    off_target_rejections: list[OffTargetRejection]
    duplicate_search_result_skips: int
    duplicate_claim_skips: int
    empty_evidence_tool_calls: int
    url_selector_extract_attempts: int
    url_selector_full_page_extracts: int
    url_selector_extract_failures: int
    evidence_full_page_extracts: int

class ResearchState(TypedDict):
    company: str
    requirement: str
    positive_when: str
    negative_when: str
    does_not_count: list[str]
    skills: NotRequired[list[str]]
    additional_evidence_needed: NotRequired[list[str]]
    search_documents: Annotated[dict[str, SearchDocument], or_]

    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    verified_evidence: Annotated[list[Evidence], add]
    verified_claims: list[str]
    verifier_judgments: Annotated[list[VerifierJudgment], add]
    verifier_sample_supported: NotRequired[VerifierJudgment | None]
    verifier_sample_wrong_company: NotRequired[VerifierJudgment | None]
    verifier_sample_unsupported: NotRequired[VerifierJudgment | None]
    unclear_ownership_judgments: Annotated[list[UnclearOwnershipJudgment], add]

    sufficient: bool | None
    satisfied: bool | None
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
    url_selector_decisions: Annotated[list[UrlSelectorDecision], add]
    query_generator_decisions: Annotated[list[QueryGeneratorDecision], add]
    evidence_extractor_decisions: Annotated[list[EvidenceExtractorDecision], add]
    research_agent_steps: Annotated[list[ResearchAgentStep], add]
    search_queries_used: Annotated[list[str], add]
    evidence_full_page_extracts: Annotated[int, add]


class PlannerAgentState(AgentState):
    research_plan: NotRequired[ResearchPlan]


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
    verified_claims: NotRequired[list[str]]
    satisfied: bool

class FitScoreUpdate(TypedDict):
    passed: bool
    fit_score: int
    reason: str