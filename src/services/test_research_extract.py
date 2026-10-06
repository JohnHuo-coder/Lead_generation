from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_test_research_extract_llm
from prompts.test_research import TEST_RESEARCH_PAGE_EXTRACT_PROMPT
from schemas.test_research_schemas import PageEvidenceItem


def extract_page_evidence(
    *,
    company: str,
    research_focus: str,
    url: str,
    content: str,
    prior_verified_claims: list[str],
) -> list[PageEvidenceItem]:
    already = (
        "\n".join(f"- {claim}" for claim in prior_verified_claims)
        if prior_verified_claims
        else "- none"
    )
    result = structured_test_research_extract_llm.invoke([
        SystemMessage(content=TEST_RESEARCH_PAGE_EXTRACT_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Research focus: {research_focus}\n"
            f"URL: {url}\n\n"
            f"Already verified claims (do not repeat):\n{already}\n\n"
            f"Page content:\n{content}"
        )),
    ])
    return result.evidence
