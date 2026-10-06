from langgraph.graph import END, START, StateGraph

from components.nodes import test_research_node
from components.state import TestResearchInput, TestResearchOutput, TestResearchState

builder = StateGraph(
    TestResearchState,
    input_schema=TestResearchInput,
    output_schema=TestResearchOutput,
)
builder.add_node("test_research", test_research_node)
builder.add_edge(START, "test_research")
builder.add_edge("test_research", END)

test_research_subgraph = builder.compile()
