from pydantic import BaseModel, Field


class RfpResult(BaseModel):
    rfp_url: str | None = Field(
        default=None,
        description=(
            "URL only if extract or crawl already showed an inquiry control "
            "on this hotel's official meetings page, or verified this hotel's "
            "Cvent /venues/ page. Null if that was not verified. Do not guess."
        ),
    )
    summarization: str = Field(
        description=(
            "Short summary of the search: what was checked, why this URL was "
            "chosen or why no reliable route was found."
        ),
    )
