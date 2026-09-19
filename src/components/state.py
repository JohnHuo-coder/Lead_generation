from typing import Annotated, TypedDict
from operator import add, or_
from langchain.agents import AgentState

from schemas.research_schemas import Evidence, EvidenceCheckFailure, SearchDocument

class ResearchAgentState(AgentState):
    tool_call_count: Annotated[int, add]
    search_documents: Annotated[dict[str, SearchDocument], or_]
    company: str
    location: str
    collaboration_intent: str
    requirement: str
    verified_evidence: Annotated[list[Evidence], add]
    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    batch_result_id_match_failures: Annotated[int, add]
    excerpt_derivation_checks: Annotated[int, add]
    evidence_full_snippet_verifications: Annotated[int, add]
    evidence_full_page_extracts: Annotated[int, add]


class ResearchState(TypedDict):
    company: str
    location: str
    collaboration_intent: str
    requirement: str
    additional_evidence_needed: list[str]
    search_documents: Annotated[dict[str, SearchDocument], or_]

    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    verified_evidence: Annotated[list[Evidence], add]

    sufficient: bool | None
    search_tool_call_count: int

    batch_result_id_match_failures: Annotated[int, add]
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
