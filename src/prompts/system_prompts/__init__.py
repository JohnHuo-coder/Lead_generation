"""Requirement-specific research prompts.

Set RESEARCH_PROMPT_PACK before importing the graph:

- meeting_capacity_catering (default) — meeting/event space + capacity + catering
- meeting_capacity — meeting/event space + capacity only
- amenities — on-site spa / pool / gym (or other amenities named in the requirement)
"""

from __future__ import annotations

import os
from importlib import import_module

from prompts.system_prompts.shared import (
    EXCERPT_DERIVATION_SYSTEM_PROMPT,
    RESEARCH_FINAL_HUMAN_REMINDER,
    VERIFICATION_SYSTEM_PROMPT,
)

PROMPT_PACKS = {
    "meeting_capacity_catering": "prompts.system_prompts.meeting_capacity_catering",
    "meeting_capacity": "prompts.system_prompts.meeting_capacity",
    "amenities": "prompts.system_prompts.amenities",
}

ACTIVE_PROMPT_PACK = os.environ.get("RESEARCH_PROMPT_PACK", "meeting_capacity_catering").strip()
if ACTIVE_PROMPT_PACK not in PROMPT_PACKS:
    raise ValueError(
        f"Unknown RESEARCH_PROMPT_PACK={ACTIVE_PROMPT_PACK!r}. "
        f"Use one of: {', '.join(PROMPT_PACKS)}"
    )

_pack = import_module(PROMPT_PACKS[ACTIVE_PROMPT_PACK])

RESEARCH_AGENT_SYSTEM_PROMPT = _pack.RESEARCH_AGENT_SYSTEM_PROMPT
RESEARCH_FINAL_SYSTEM_PROMPT = _pack.RESEARCH_FINAL_SYSTEM_PROMPT
QUERY_GENERATOR_SYSTEM_PROMPT = _pack.QUERY_GENERATOR_SYSTEM_PROMPT
URL_SELECTOR_SYSTEM_PROMPT = _pack.URL_SELECTOR_SYSTEM_PROMPT
SEARCH_BATCH_EVIDENCE_PROMPT = _pack.SEARCH_BATCH_EVIDENCE_PROMPT
