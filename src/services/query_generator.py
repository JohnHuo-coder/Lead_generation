from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_query_generator_llm
from prompts.system_prompts import QUERY_GENERATOR_SYSTEM_PROMPT
from schemas.research_schemas import QueryGeneratorResult


def _format_verified_claims(claims: list[str]) -> str:
    if not claims:
        return "- none"
    return "\n".join(f"- {claim}" for claim in claims)


def _format_prior_queries(queries: list[str]) -> str:
    if not queries:
        return "- none"
    return "\n".join(f"- {query}" for query in queries)


def _format_prior_urls(urls: list[str]) -> str:
    if not urls:
        return "- none"
    return "\n".join(f"- {url}" for url in urls)


def generate_search_query(
    *,
    company: str,
    requirement: str,
    search_focus: str,
    prior_verified_claims: list[str],
    prior_queries: list[str],
    prior_source_urls: list[str],
) -> QueryGeneratorResult:
    return structured_query_generator_llm.invoke([
        SystemMessage(content=QUERY_GENERATOR_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Requirement: {requirement}\n"
            f"Search focus: {search_focus}\n\n"
            f"Already verified claims:\n"
            f"{_format_verified_claims(prior_verified_claims)}\n\n"
            f"Queries already used this run (do not repeat):\n"
            f"{_format_prior_queries(prior_queries)}\n\n"
            f"URLs already seen from earlier searches (use to infer official domains):\n"
            f"{_format_prior_urls(prior_source_urls)}"
        )),
    ])
