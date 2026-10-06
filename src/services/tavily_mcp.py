from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlencode

from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from components.constants import TAVILY_RFP_TOOLS

load_dotenv()

_client: MultiServerMCPClient | None = None
_tools: list[BaseTool] | None = None

TAVILY_MCP_URL = "https://mcp.tavily.com/mcp/"


def _tavily_mcp_url() -> str:
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for the Tavily MCP connection.")
    return f"{TAVILY_MCP_URL}?{urlencode({'tavilyApiKey': api_key})}"


@lru_cache(maxsize=1)
def _mcp_client() -> MultiServerMCPClient:
    global _client
    if _client is None:
        _client = MultiServerMCPClient({
            "tavily": {
                "url": _tavily_mcp_url(),
                "transport": "http",
            }
        })
    return _client


async def load_tavily_rfp_tools() -> list[BaseTool]:
    global _tools
    if _tools is None:
        all_tools = await _mcp_client().get_tools()
        _tools = [tool for tool in all_tools if tool.name in TAVILY_RFP_TOOLS]
    return _tools
