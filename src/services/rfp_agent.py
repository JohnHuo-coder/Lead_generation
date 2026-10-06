from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from components.constants import MAX_RFP_TAVILY_CALLS, TAVILY_RFP_TOOLS
from components.rfp_tools import save_contact_email, think_tool
from components.state import RfpAgentState
from llm.models import llm
from prompts.rfp import RFP_AGENT_SYSTEM_PROMPT, RFP_FINAL_HUMAN_REMINDER
from schemas.rfp_schemas import RfpResult
from services.tavily_mcp import load_tavily_rfp_tools

_rfp_agent = None


def _system_prompt() -> str:
    return RFP_AGENT_SYSTEM_PROMPT.format(
        date=date.today().isoformat(),
        max_tavily_calls=MAX_RFP_TAVILY_CALLS,
    )


def _tavily_calls_used(messages: list) -> int:
    return sum(
        1
        for message in messages
        if isinstance(message, ToolMessage) and message.name in TAVILY_RFP_TOOLS
    )


@wrap_model_call
async def control_rfp_tavily(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    model_settings = {
        **(request.model_settings or {}),
        "parallel_tool_calls": False,
    }
    if _tavily_calls_used(request.messages) < MAX_RFP_TAVILY_CALLS:
        return await handler(request.override(model_settings=model_settings))

    remaining_tools = [
        tool
        for tool in request.tools
        if tool.name not in TAVILY_RFP_TOOLS
    ]
    return await handler(
        request.override(
            tools=remaining_tools,
            system_message=SystemMessage(content=_system_prompt()),
            messages=[
                *request.messages,
                HumanMessage(content=RFP_FINAL_HUMAN_REMINDER),
            ],
            tool_choice="RfpResult",
            model_settings=model_settings,
        )
    )


async def get_rfp_agent():
    global _rfp_agent
    if _rfp_agent is None:
        tavily_tools = await load_tavily_rfp_tools()
        allowed = {tool.name for tool in tavily_tools}
        missing = TAVILY_RFP_TOOLS - allowed
        if missing:
            raise RuntimeError(
                "Tavily MCP did not expose required tools: "
                + ", ".join(sorted(missing))
            )
        _rfp_agent = create_agent(
            model=llm,
            tools=[*tavily_tools, think_tool, save_contact_email],
            middleware=[control_rfp_tavily],
            response_format=ToolStrategy(RfpResult),
            state_schema=RfpAgentState,
            system_prompt=_system_prompt(),
        )
    return _rfp_agent
