from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

from components.state import ResearchAgentState
from services.search_evidence_extractor import extract_evidence_from_search_batch

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

    batch_evidence = extract_evidence_from_search_batch(
        company=runtime.state.get("company", ""),
        collaboration_intent=runtime.state.get("collaboration_intent", ""),
        requirement=runtime.state.get("requirement", ""),
        batch_documents=search_documents,
    )
    if batch_evidence:
        evidence_summary = "\n".join(
            f"- {item.claim} (result_id={item.result_id})"
            for item in batch_evidence
        )
        result_string += (
            "\n\nEvidence extracted from this search batch:\n"
            f"{evidence_summary}"
        )

    update: dict = {
        "tool_call_count": 1,
        "search_documents": search_documents,
        "messages": [
            ToolMessage(
                content=result_string,
                tool_call_id=runtime.tool_call_id,
            )
        ],
    }
    if batch_evidence:
        update["candidate_evidence"] = batch_evidence

    return Command(update=update)
