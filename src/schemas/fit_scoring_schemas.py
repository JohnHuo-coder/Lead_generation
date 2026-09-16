from pydantic import BaseModel, Field

class FitScoreResult(BaseModel):
    score: int = Field(
        description="A score from 0 to 100 indicating how well the evidence aligns with the requirement."
    )
    reason: str = Field(
        description="A concise explanation of the score"
    )
    supporting_facts: list[str] = Field(
        description="A list of the most important factual claims that support the score."
    )
