from typing import Literal

from pydantic import BaseModel, Field


class DimensionScores(BaseModel):
    venue_suitability: int = Field(ge=1, le=10)
    brand_alignment: int = Field(ge=1, le=10)
    wellness_synergy: int = Field(ge=1, le=10)
    audience_fit: int = Field(ge=1, le=10)
    operational_feasibility: int = Field(ge=1, le=10)


class EvidenceItem(BaseModel):
    dimension: Literal[
        "venue_suitability",
        "brand_alignment",
        "wellness_synergy",
        "audience_fit",
        "operational_feasibility",
    ]
    quote: str
    source_section: Literal[
        "about_text",
        "meetings_and_events_content",
        "amenities_content",
        "location_content",
    ]
    reason: str


class EvalResult(BaseModel):
    scores: DimensionScores
    total_score: int = Field(ge=1, le=100)
    overall_recommendation: str
    evidence: list[EvidenceItem]


class IcebreakerEmail(BaseModel):
    subject: str = Field(description="Short, specific subject line")
    body: str = Field(
        description="Email body: one concrete fact from the site, then brief intro, then clear collaboration intent"
    )