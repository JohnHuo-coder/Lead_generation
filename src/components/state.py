from typing import Annotated, TypedDict
from operator import add, or_
from langchain.agents import AgentState

from schemas.research_schemas import Evidence, EvidenceCheckFailure, SearchDocument

class ResearchAgentState(AgentState):
    tool_call_count: Annotated[int, add]
    search_documents: Annotated[dict[str, SearchDocument], or_]


class ResearchState(TypedDict):
    company: str
    collaboration_intent: str
    requirement: str
    additional_evidence_needed: list[str]
    search_documents: Annotated[dict[str, SearchDocument], or_]


    candidate_evidence: list[Evidence]
    failed_evidence_checks: Annotated[list[EvidenceCheckFailure], add]
    verified_evidence: Annotated[list[Evidence], add]
    
    sufficient: bool | None
    search_tool_call_count: int


class CheckSourceExcerptState(TypedDict):
    evidence: Evidence
    search_documents: Annotated[dict[str, SearchDocument], or_]


class FitScoreState(TypedDict):
    company: str
    collaboration_intent: str
    requirement: str
    verified_evidence: list[Evidence]
    fit_score: int
    reason: str
    supporting_facts: list[str]