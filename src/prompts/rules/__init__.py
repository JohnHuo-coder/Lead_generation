from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_RULES_DIR = Path(__file__).parent
_ROLE_HEADING = re.compile(r"^##\s+(\w+)\s*$", re.MULTILINE)
_EMPTY_RULES = "- none"


@dataclass(frozen=True)
class DomainSkill:
    name: str
    description: str
    sections: dict[str, str]


def _parse_sections(body: str) -> dict[str, str]:
    matches = list(_ROLE_HEADING.finditer(body))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[match.end():end].strip()
        if text:
            sections[match.group(1)] = text
    return sections


def _parse_skill_file(path: Path) -> DomainSkill:
    text = path.read_text(encoding="utf-8")
    name = path.stem
    description = ""
    body = text.strip()
    if text.startswith("---"):
        _, frontmatter, remainder = text.split("---", 2)
        for line in frontmatter.splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip()
            value = value.strip()
            if key == "name":
                name = value or name
            elif key == "description":
                description = value
        body = remainder.strip()
    return DomainSkill(
        name=name,
        description=description,
        sections=_parse_sections(body),
    )


SKILLS: dict[str, DomainSkill] = {
    skill.name: skill
    for skill in (
        _parse_skill_file(path)
        for path in sorted(_RULES_DIR.glob("*.md"))
    )
}


def format_skill_catalog() -> str:
    if not SKILLS:
        return "- none"
    return "\n".join(
        f"- {skill.name}: {skill.description}"
        for skill in SKILLS.values()
    )


def resolve_skill_ids(skill_ids: list[str] | None) -> list[str]:
    resolved: list[str] = []
    for skill_id in skill_ids or []:
        name = skill_id.strip()
        if name in SKILLS and name not in resolved:
            resolved.append(name)
    return resolved


def load_domain_rules(skill_ids: list[str] | None, role: str) -> str:
    blocks = [
        SKILLS[name].sections[role]
        for name in resolve_skill_ids(skill_ids)
        if role in SKILLS[name].sections
    ]
    return "\n\n".join(blocks)


def with_domain_rules(
    prompt: str,
    skill_ids: list[str] | None,
    role: str,
) -> str:
    extra = load_domain_rules(skill_ids, role) or _EMPTY_RULES
    if "{domain_rules}" not in prompt:
        return f"{prompt.rstrip()}\n\n{extra}"
    return prompt.replace("{domain_rules}", extra)
