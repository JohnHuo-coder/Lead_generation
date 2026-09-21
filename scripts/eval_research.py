"""Run offline LangSmith evals for the B2B research graph.

This script only runs the research target. Assertion grading is handled by the
LangSmith dataset evaluator configured in the UI (Assertions / LLM-as-a-Judge).
Configure the OpenAI API key in LangSmith workspace settings for that judge.

Usage:
    uv run python scripts/eval_research.py
    uv run python scripts/eval_research.py --experiment-prefix b2b-leadgen-v2
    uv run python scripts/eval_research.py --max-concurrency 5
    uv run python scripts/eval_research.py --verbose
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from dotenv import load_dotenv
from langsmith import evaluate, traceable

load_dotenv()

DEFAULT_DATASET = "b2b-leadgen-engine-dataset"
DEFAULT_EXPERIMENT_PREFIX = "b2b-leadgen-engine-eval"
DEFAULT_MAX_CONCURRENCY = int(os.getenv("EVAL_MAX_CONCURRENCY", "5"))


def _serialize_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def _build_pipeline_stats(state: dict[str, Any]) -> dict[str, int]:
    return {
        "batch_result_id_match_failures": int(
            state.get("batch_result_id_match_failures", 0) or 0
        ),
        "excerpt_derivation_checks": int(state.get("excerpt_derivation_checks", 0) or 0),
        "evidence_full_snippet_verifications": int(
            state.get("evidence_full_snippet_verifications", 0) or 0
        ),
        "evidence_full_page_extracts": int(
            state.get("evidence_full_page_extracts", 0) or 0
        ),
    }


def _format_research_output(state: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    output: dict[str, Any] = {
        "verified_evidence": [
            _serialize_item(item) for item in state.get("verified_evidence") or []
        ],
        "failed_evidence_checks": [
            _serialize_item(item) for item in state.get("failed_evidence_checks") or []
        ],
        "sufficient": state.get("sufficient"),
        "reason": state.get("sufficient_reason") or "",
    }
    if verbose:
        output["company"] = state.get("company")
        output["additional_evidence_needed"] = state.get("additional_evidence_needed") or []
        output["search_tool_call_count"] = state.get("search_tool_call_count", 0)
        output["pipeline_stats"] = _build_pipeline_stats(state)
    return output


def _make_run_research(*, verbose: bool):
    @traceable(name="b2b_research_eval_target")
    def run_research(inputs: dict[str, Any]) -> dict[str, Any]:
        from graphs.main_graph import react_graph

        graph_input = {
            "company": inputs["company"],
            "collaboration_intent": inputs["collaboration_intent"],
            "requirement": inputs["requirement"],
        }
        if inputs.get("additional_evidence_needed") is not None:
            graph_input["additional_evidence_needed"] = inputs["additional_evidence_needed"]

        state = react_graph.invoke(
            graph_input,
            config={"recursion_limit": 12},
        )
        return _format_research_output(state, verbose=verbose)

    return run_research


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LangSmith evals for the research graph.")
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"LangSmith dataset name (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--experiment-prefix",
        default=DEFAULT_EXPERIMENT_PREFIX,
        help=f"Experiment prefix in LangSmith (default: {DEFAULT_EXPERIMENT_PREFIX})",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_MAX_CONCURRENCY,
        help=f"Maximum concurrent examples (default: {DEFAULT_MAX_CONCURRENCY})",
    )
    parser.add_argument(
        "--description",
        default=(
            "Offline eval for B2B research graph. "
            "Assertion grading uses the dataset's LangSmith Assertions evaluator."
        ),
        help="Experiment description shown in LangSmith.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Include debug fields in outputs (company, pipeline_stats, "
            "search_tool_call_count, additional_evidence_needed)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not os.getenv("LANGSMITH_TRACING"):
        os.environ["LANGSMITH_TRACING"] = "true"
    if not os.getenv("LANGSMITH_PROJECT"):
        os.environ["LANGSMITH_PROJECT"] = args.experiment_prefix

    results = evaluate(
        _make_run_research(verbose=args.verbose),
        data=args.dataset,
        experiment_prefix=args.experiment_prefix,
        description=args.description,
        max_concurrency=args.max_concurrency,
    )

    print(f"Experiment: {results.experiment_name}")
    print(
        "Assertion grading: LangSmith dataset evaluator 'Assertions' "
        "(LLM-as-a-Judge). Check feedback key 'assertions_passed' in the UI."
    )
    print(
        "View results in LangSmith under the dataset Experiments tab "
        f"for dataset '{args.dataset}'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
