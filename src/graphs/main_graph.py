from langgraph.graph import START, StateGraph, END

from components.state import OverallState, ResearchState, ResearchInput, ResearchOutput
from components.nodes import search_node, search_to_fit_score, fit_scoring_node, fit_score_to_contact_discovery, contact_discovery_node


research_builder = StateGraph(
    ResearchState,
    input_schema=ResearchInput,
    output_schema=ResearchOutput,
)

research_builder.add_node("search", search_node)

research_builder.add_edge(START, "search")
research_builder.add_edge("search", END)
research_subgraph = research_builder.compile()


builder = StateGraph(OverallState)
builder.add_node("search", research_subgraph)
builder.add_node("fit_scoring", fit_scoring_node)
builder.add_node("contact_discovery", contact_discovery_node)

builder.add_edge(START, "search")
builder.add_conditional_edge("search", search_to_fit_score)
builder.add_conditional_edge("fit_score", fit_score_to_contact_discovery)


builder.add_edge("search", END)


full_graph = builder.compile()
