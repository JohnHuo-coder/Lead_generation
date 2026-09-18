from langgraph.graph import START, StateGraph, END

from components.state import ResearchState
from components.nodes import search_node


builder = StateGraph(ResearchState)
builder.add_node("search", search_node)

builder.add_edge(START, "search")
builder.add_edge("search", END)


react_graph = builder.compile()
