from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_query_generator_llm
from prompts.research import QUERY_GENERATOR_SYSTEM_PROMPT
from prompts.rules import with_domain_rules
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


def _retrieval_hint(prior_queries: list[str], prior_source_urls: list[str]) -> str:
    if not prior_queries:
        return (
            "This is the first query: open keywords, no site:. Keep location "
            "disambiguators (soi, street number, neighborhood). Drop only "
            "parent-company ('by …') and extra marketing descriptors."
        )
    if not prior_source_urls:
        return (
            "Earlier searches returned no on-target pages. Keep location "
            "tokens and try Cvent or site: on the official domain "
            "(meetings, events, facilities, faqs, factsheets)."
        )
    return (
        "After the open query, you may use site: on the official domain "
        "(meetings/events/facilities/faqs) or Cvent. If the official domain "
        "is already known and inventory is still missing, prefer "
        "site:{domain} faqs OR facilities OR meetings, not gallery or "
        "guest-room pages."
    )


def generate_search_query(
    *,
    company: str,
    search_focus: str,
    prior_verified_claims: list[str],
    prior_queries: list[str],
    prior_source_urls: list[str],
    skill_ids: list[str] | None = None,
) -> QueryGeneratorResult:
    return structured_query_generator_llm.invoke([
        SystemMessage(
            content=with_domain_rules(
                QUERY_GENERATOR_SYSTEM_PROMPT, skill_ids, "query"
            )
        ),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Search focus: {search_focus}\n\n"
            f"Retrieval hint: {_retrieval_hint(prior_queries, prior_source_urls)}\n\n"
            f"Already verified claims:\n"
            f"{_format_verified_claims(prior_verified_claims)}\n\n"
            f"Queries already used this run (do not repeat):\n"
            f"{_format_prior_queries(prior_queries)}\n\n"
            f"URLs already seen from earlier searches (use to infer official domains):\n"
            f"{_format_prior_urls(prior_source_urls)}"
        )),
    ])
