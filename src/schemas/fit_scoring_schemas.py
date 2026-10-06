from pydantic import BaseModel, Field


class FitScoreResult(BaseModel):
    passed: bool = Field(
        description=(
            "Whether the property meets the requirement. True only if the verified "
            "claims establish that it satisfies the requirement. False if the claims "
            "show it does not — including complete negative evidence such as no "
            "meeting space, insufficient capacity, no catering, or a required "
            "amenity not on site. Completeness of evidence is not a pass."
        )
    )
    score: int = Field(
        ge=0,
        le=100,
        description=(
            "0-100 alignment with the requirement. Use 75-100 when passed=true, "
            "0-74 when passed=false."
        ),
    )
    reason: str = Field(
        description=(
            "Concise explanation of passed and score, citing the verified claims "
            "that decide the outcome."
        )
    )
