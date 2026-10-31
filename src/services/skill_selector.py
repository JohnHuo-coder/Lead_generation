from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_skill_choice_llm
from prompts.rules import format_skill_catalog, resolve_skill_ids


def choose_domain_skills(
    *,
    requirement: str,
    positive_when: str = "",
    negative_when: str = "",
    does_not_count: list[str] | None = None,
) -> list[str]:
    catalog = format_skill_catalog()
    skipped = (
        "\n".join(f"- {item}" for item in does_not_count)
        if does_not_count
        else "- none"
    )
    result = structured_skill_choice_llm.invoke([
        SystemMessage(
            content=(
                "Choose domain skills for one research requirement.\n"
                "Attach a skill only when its description matches.\n"
                "You may attach more than one, or none.\n\n"
                f"Available skills:\n{catalog}"
            )
        ),
        HumanMessage(
            content=(
                f"Requirement: {requirement}\n"
                f"Met when: {positive_when}\n"
                f"Not met when: {negative_when}\n"
                f"Does not count:\n{skipped}"
            )
        ),
    ])
    return resolve_skill_ids(result.skills)
