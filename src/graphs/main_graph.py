from langgraph.graph import START, StateGraph, END

from components.state import ResearchState, ResearchInput, ResearchOutput
from components.nodes import search_node


research_builder = StateGraph(
    ResearchState,
    input_schema=ResearchInput,
    output_schema=ResearchOutput,
)

research_builder.add_node("search", search_node)

research_builder.add_edge(START, "search")
research_builder.add_edge("search", END)
research_subgraph = research_builder.compile()
