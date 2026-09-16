from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

from components.state import ResearchAgentState
tavily_client = TavilyClient()


@tool
def web_search(query: str, runtime: ToolRuntime[ResearchAgentState]) -> dict:
    """Search the web for pages about a company and return source URLs and excerpts."""
    response = tavily_client.search(query, max_results=5)
    search_documents = {}
    tool_results = []
    for index, item in enumerate(response["results"]):
        result_id = f"{runtime.tool_call_id}_{index}"
        document = {
            "query": query,
            "title": item["title"],
            "url": item["url"],
            "content": item["content"],
        }
        search_documents[result_id] = document
        tool_results.append(
            f"result_id: {result_id}\n"
            f"title: {document['title']}\n"
            f"url: {document['url']}\n"
            f"content: {document['content']}"
        )
    result_string = "\n\n".join(tool_results)

    return Command(
        update={
            "tool_call_count": 1,
            "search_documents": search_documents,
            "messages": [
                ToolMessage(
                    content=result_string,
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )