from pydantic import BaseModel, Field


class FitScoreResult(BaseModel):
    score: int = Field(
        ge=0,
        le=100,
        description=(
            "0-100 alignment with the requirement. Research already decided "
            "whether the property meets it. Use 75-100 when satisfied=true, "
            "0-74 when satisfied=false."
        ),
    )
    reason: str = Field(
        description=(
            "Concise explanation of the score, citing the verified claims "
            "that decide how well the property aligns with the requirement."
        )
    )
