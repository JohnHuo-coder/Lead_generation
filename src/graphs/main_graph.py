from langgraph.graph import START, StateGraph, END

from components.state import ResearchState
from components.nodes import fit_score_node, search_node

MAX_RESEARCH_ROUNDS = 3


def route_after_search(state: ResearchState) -> str:
    if (
        state.get("sufficient") is False
        and state.get("research_rounds", 0) < MAX_RESEARCH_ROUNDS
    ):
        return "search"
    return "fit_score"


builder = StateGraph(ResearchState)
builder.add_node("search", search_node)
builder.add_node("fit_score", fit_score_node)

builder.add_edge(START, "search")
builder.add_conditional_edges(
    "search",
    route_after_search,
    {
        "search": "search",
        "fit_score": "fit_score",
    },
)
builder.add_edge("fit_score", END)


react_graph = builder.compile()
