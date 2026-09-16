from langgraph.graph import START, StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver

from components.state import ResearchState
from components.nodes import search_node, fit_score_node, continue_to_check_source_excerpts, check_source_excerpts


builder = StateGraph(ResearchState)
builder.add_node("search", search_node)
builder.add_node("check_source_excerpts", check_source_excerpts)

builder.add_edge(START, "search")
builder.add_conditional_edges("search", continue_to_check_source_excerpts, ["check_source_excerpts"])
builder.add_edge("check_source_excerpts", END)


react_graph = builder.compile()