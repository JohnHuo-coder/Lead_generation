from typing import Annotated, TypedDict
from operator import add, or_
from langchain.agents import AgentState

from schemas.research_schemas import Evidence, EvidenceCheckFailure, SearchDocument

class ResearchAgentState(AgentState):
    tool_call_count: Annotated[int, add]
    search_documents: Annotated[dict[str, SearchDocument], or_]
    company: str
    collaboration_intent: str
    requirement: str
    verified_evidence: Annotated[list[Evidence], add]
    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    batch_result_id_match_failures: Annotated[int, add]
    off_target_company_rejections: Annotated[int, add]
    duplicate_search_result_skips: Annotated[int, add]
    duplicate_claim_skips: Annotated[int, add]
    empty_evidence_tool_calls: Annotated[int, add]
    fallback_extract_attempts: Annotated[int, add]
    fallback_verified_hits: Annotated[int, add]
    url_selector_extract_attempts: Annotated[int, add]
    url_selector_full_page_extracts: Annotated[int, add]
    url_selector_extract_failures: Annotated[int, add]
    search_queries_used: Annotated[list[str], add]
    excerpt_derivation_checks: Annotated[int, add]
    evidence_full_snippet_verifications: Annotated[int, add]
    evidence_full_page_extracts: Annotated[int, add]


class ResearchState(TypedDict):
    company: str
    collaboration_intent: str
    requirement: str
    additional_evidence_needed: list[str]
    search_documents: Annotated[dict[str, SearchDocument], or_]

    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    verified_evidence: Annotated[list[Evidence], add]

    sufficient: bool | None
    sufficient_reason: str
    search_tool_call_count: int

    batch_result_id_match_failures: Annotated[int, add]
    off_target_company_rejections: Annotated[int, add]
    duplicate_search_result_skips: Annotated[int, add]
    duplicate_claim_skips: Annotated[int, add]
    empty_evidence_tool_calls: Annotated[int, add]
    fallback_extract_attempts: Annotated[int, add]
    fallback_verified_hits: Annotated[int, add]
    url_selector_extract_attempts: Annotated[int, add]
    url_selector_full_page_extracts: Annotated[int, add]
    url_selector_extract_failures: Annotated[int, add]
    search_queries_used: Annotated[list[str], add]
    excerpt_derivation_checks: Annotated[int, add]
    evidence_full_snippet_verifications: Annotated[int, add]
    evidence_full_page_extracts: Annotated[int, add]


class FitScoreState(TypedDict):
    company: str
    collaboration_intent: str
    requirement: str
    verified_evidence: list[Evidence]
    fit_score: int
    reason: str
    supporting_facts: list[str]
