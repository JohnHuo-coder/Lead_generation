from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from components.constants import (
    MAX_TEST_RESEARCH_INSPECT_CALLS,
    MAX_TEST_RESEARCH_SEARCH_CALLS,
    MAX_TEST_RESEARCH_TOOL_CALLS,
)
from components.state import TestResearchAgentState
from components.test_research_tools import (
    inspect_web_page,
    think_tool,
    web_search,
    write_evidence,
)
from llm.models import llm
from prompts.test_research import (
    TEST_RESEARCH_INSPECT_BUDGET_REMINDER,
    TEST_RESEARCH_SEARCH_BUDGET_REMINDER,
    TEST_RESEARCH_SYSTEM_PROMPT,
    TEST_RESEARCH_TOOL_BUDGET_REMINDER,
)
from schemas.test_research_schemas import TestResearchResult

_test_research_agent = None

_RESEARCH_TOOL_NAMES = frozenset({
    "web_search",
    "inspect_web_page",
    "write_evidence",
    "think_tool",
})


def _system_prompt() -> str:
    return TEST_RESEARCH_SYSTEM_PROMPT.format(
        date=date.today().isoformat(),
        max_search_calls=MAX_TEST_RESEARCH_SEARCH_CALLS,
        max_inspect_calls=MAX_TEST_RESEARCH_INSPECT_CALLS,
        max_tool_calls=MAX_TEST_RESEARCH_TOOL_CALLS,
    )


def research_tool_counts(messages: list) -> dict[str, int]:
    counts = {name: 0 for name in _RESEARCH_TOOL_NAMES}
    for message in messages:
        if isinstance(message, ToolMessage) and message.name in counts:
            counts[message.name] += 1
    return counts


def _reminder_already_present(messages: list, reminder: str) -> bool:
    return any(
        isinstance(message, HumanMessage) and message.content == reminder
        for message in messages
    )


@wrap_model_call
async def control_test_research_search(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    model_settings = {
        **(request.model_settings or {}),
        "parallel_tool_calls": False,
    }
    counts = research_tool_counts(request.messages)
    total_used = sum(counts.values())
    blocked: set[str] = set()
    reminders: list[str] = []

    if total_used >= MAX_TEST_RESEARCH_TOOL_CALLS:
        blocked = set(_RESEARCH_TOOL_NAMES)
        reminders.append(TEST_RESEARCH_TOOL_BUDGET_REMINDER)
    else:
        if counts["web_search"] >= MAX_TEST_RESEARCH_SEARCH_CALLS:
            blocked.add("web_search")
            reminders.append(TEST_RESEARCH_SEARCH_BUDGET_REMINDER)
        if counts["inspect_web_page"] >= MAX_TEST_RESEARCH_INSPECT_CALLS:
            blocked.add("inspect_web_page")
            reminders.append(TEST_RESEARCH_INSPECT_BUDGET_REMINDER)

    if not blocked:
        return await handler(request.override(model_settings=model_settings))

    extra_messages = [
        HumanMessage(content=reminder)
        for reminder in reminders
        if not _reminder_already_present(request.messages, reminder)
    ]
    override: dict = {
        "tools": [tool for tool in request.tools if tool.name not in blocked],
        "system_message": SystemMessage(content=_system_prompt()),
        "model_settings": model_settings,
    }
    if extra_messages:
        override["messages"] = [*request.messages, *extra_messages]
    if total_used >= MAX_TEST_RESEARCH_TOOL_CALLS:
        override["tool_choice"] = "TestResearchResult"
    return await handler(request.override(**override))


async def get_test_research_agent():
    global _test_research_agent
    if _test_research_agent is None:
        _test_research_agent = create_agent(
            model=llm,
            tools=[web_search, write_evidence, inspect_web_page, think_tool],
            middleware=[control_test_research_search],
            response_format=ToolStrategy(TestResearchResult),
            state_schema=TestResearchAgentState,
            system_prompt=_system_prompt(),
        )
    return _test_research_agent
