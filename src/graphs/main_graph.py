from hashlib import sha256
from typing import Any
from uuid import uuid4

from langgraph.graph import START, StateGraph, END

from components.state import ResearchState
from components.nodes import search_node


builder = StateGraph(ResearchState)
builder.add_node("search", search_node)

builder.add_edge(START, "search")
builder.add_edge("search", END)


react_graph = builder.compile()


def _requirement_id(requirement: str) -> str:
    return sha256(requirement.strip().encode("utf-8")).hexdigest()[:12]


def _root_config(
    input_data: dict[str, Any],
    *,
    batch_id: str,
    execution_mode: str,
) -> dict[str, Any]:
    return {
        "run_name": "lead_research",
        "metadata": {
            "environment": execution_mode,
            "batch_id": batch_id,
            "company": input_data["company"],
            "requirement_id": _requirement_id(input_data["requirement"]),
        },
    }


def run_research(
    input_data: dict[str, Any],
    *,
    execution_mode: str = "production",
) -> dict[str, Any]:
    return react_graph.invoke(
        input_data,
        config=_root_config(
            input_data,
            batch_id=uuid4().hex,
            execution_mode=execution_mode,
        ),
    )


async def run_research_batch(
    inputs: list[dict[str, Any]],
    *,
    execution_mode: str = "production",
    batch_id: str | None = None,
) -> list[dict[str, Any]]:
    shared_batch_id = batch_id or uuid4().hex
    configs = [
        _root_config(
            input_data,
            batch_id=shared_batch_id,
            execution_mode=execution_mode,
        )
        for input_data in inputs
    ]
    return await react_graph.abatch(inputs, config=configs)
