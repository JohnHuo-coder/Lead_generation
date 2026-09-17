from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

CHECK_STAGE_LABELS = {
    "evidence_validation": "Evidence validation",
    "snippet_excerpt": "Snippet excerpt check",
    "full_page_excerpt": "Full-page excerpt check",
    "claim_verification": "Claim verification",
}

FAILURE_REASON_LABELS = {
    "missing_excerpts": "Missing source excerpts",
    "invalid_result_id": "Invalid result_id",
    "excerpt_not_found": "Excerpt not found in source",
    "page_extract_failed": "Full-page extract failed",
    "claim_not_supported": "Claim not supported by excerpts",
}


def _format_check_stage(stage: str | None) -> str:
    if not stage:
        return "Unknown"
    return CHECK_STAGE_LABELS.get(stage, stage)


def _format_failure_reason(reason: str | None) -> str:
    if not reason:
        return "Unknown"
    return FAILURE_REASON_LABELS.get(reason, reason)


def _serialize_evidence(item: Any) -> dict:
    if isinstance(item, BaseModel):
        return item.model_dump()
    return dict(item)


def _serialize_failure(item: Any) -> dict:
    return dict(item)


def _resolve_source_content(
    item: dict[str, Any],
    search_documents: dict[str, Any],
) -> str:
    existing_content = item.get("source_content")
    if existing_content:
        return existing_content

    document = search_documents.get(item.get("result_id", ""))
    if document:
        return document.get("content", "")
    return ""


def _enrich_evidence_item(
    item: Any,
    search_documents: dict[str, Any],
) -> dict[str, Any]:
    enriched = _serialize_evidence(item) if isinstance(item, BaseModel) else dict(item)
    enriched["source_content"] = _resolve_source_content(enriched, search_documents)
    return enriched


def build_run_report(state: dict[str, Any]) -> dict[str, Any]:
    search_documents = state.get("search_documents") or {}
    candidate_evidence = state.get("candidate_evidence") or []
    verified_evidence = state.get("verified_evidence") or []
    failed_evidence_checks = state.get("failed_evidence_checks") or []

    failure_reason_counts = Counter(
        failure.get("failure_reason", "unknown")
        for failure in failed_evidence_checks
    )
    check_stage_counts = Counter(
        failure.get("check_stage", "unknown")
        for failure in failed_evidence_checks
    )

    evidence_total = len(candidate_evidence)
    verified_count = len(verified_evidence)
    failed_count = len(failed_evidence_checks)

    return {
        "company": state.get("company"),
        "requirement": state.get("requirement"),
        "sufficient": state.get("sufficient"),
        "search_tool_call_count": state.get("search_tool_call_count", 0),
        "additional_evidence_needed": state.get("additional_evidence_needed") or [],
        "evidence_total": evidence_total,
        "verified_count": verified_count,
        "failed_count": failed_count,
        "verify_success_rate": (
            verified_count / evidence_total if evidence_total else None
        ),
        "candidate_evidence": [
            _enrich_evidence_item(item, search_documents) for item in candidate_evidence
        ],
        "verified_evidence": [
            _enrich_evidence_item(item, search_documents) for item in verified_evidence
        ],
        "failed_evidence_checks": [
            {
                **_serialize_failure(item),
                "source_content": _resolve_source_content(
                    _serialize_failure(item),
                    search_documents,
                ),
            }
            for item in failed_evidence_checks
        ],
        "failure_reason_counts": dict(failure_reason_counts),
        "check_stage_counts": dict(check_stage_counts),
    }


def build_batch_summary(
    inputs: list[dict[str, Any]],
    results: list[Any],
) -> dict[str, Any]:
    run_reports: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, result in enumerate(results):
        company = inputs[index].get("company") if index < len(inputs) else None
        if isinstance(result, Exception):
            errors.append(
                {
                    "company": company,
                    "error_type": type(result).__name__,
                    "error_message": str(result),
                }
            )
            continue

        report = build_run_report(result)
        run_reports.append(report)

    total_runs = len(results)
    successful_runs = len(run_reports)
    error_runs = len(errors)

    sufficient_values = [
        report["sufficient"]
        for report in run_reports
        if report["sufficient"] is not None
    ]
    sufficient_count = sum(1 for value in sufficient_values if value is True)
    insufficient_count = sum(1 for value in sufficient_values if value is False)

    evidence_total = sum(report["evidence_total"] for report in run_reports)
    verified_total = sum(report["verified_count"] for report in run_reports)
    failed_total = sum(report["failed_count"] for report in run_reports)
    tool_call_total = sum(report["search_tool_call_count"] for report in run_reports)
    average_tool_call_count = (
        tool_call_total / successful_runs if successful_runs else None
    )

    failure_reason_counts: Counter[str] = Counter()
    check_stage_counts: Counter[str] = Counter()
    for report in run_reports:
        failure_reason_counts.update(report["failure_reason_counts"])
        check_stage_counts.update(report["check_stage_counts"])

    def _rate(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    return {
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "error_runs": error_runs,
        "sufficient_count": sufficient_count,
        "insufficient_count": insufficient_count,
        "sufficient_rate": _rate(sufficient_count, len(sufficient_values)),
        "evidence_total": evidence_total,
        "verified_total": verified_total,
        "failed_total": failed_total,
        "verify_success_rate": _rate(verified_total, evidence_total),
        "verify_failure_rate": _rate(failed_total, evidence_total),
        "tool_call_total": tool_call_total,
        "average_tool_call_count": average_tool_call_count,
        "failure_reason_counts": dict(failure_reason_counts),
        "failure_reason_rates": {
            reason: _rate(count, failed_total)
            for reason, count in failure_reason_counts.items()
        },
        "check_stage_counts": dict(check_stage_counts),
        "check_stage_rates": {
            stage: _rate(count, failed_total)
            for stage, count in check_stage_counts.items()
        },
        "runs": run_reports,
        "errors": errors,
    }


def format_run_report(report: dict[str, Any]) -> str:
    lines = [
        f"Company: {report['company']}",
        f"Sufficient: {report['sufficient']}",
        f"Search tool calls: {report['search_tool_call_count']}",
        f"Evidence total: {report['evidence_total']}",
        f"Verified: {report['verified_count']}",
        f"Failed: {report['failed_count']}",
    ]

    if report["verify_success_rate"] is not None:
        lines.append(f"Verify success rate: {report['verify_success_rate']:.1%}")

    if report["failure_reason_counts"]:
        lines.append("Failure breakdown:")
        for reason, count in report["failure_reason_counts"].items():
            lines.append(f"  - {reason}: {count}")

    if report["failed_evidence_checks"]:
        lines.append("Failed evidence details:")
        for index, failure in enumerate(report["failed_evidence_checks"], start=1):
            lines.append(
                f"  [{index}] stage={_format_check_stage(failure.get('check_stage'))}"
            )
            lines.append(
                f"      reason={_format_failure_reason(failure.get('failure_reason'))}"
            )
            lines.append(f"      claim={failure.get('claim')}")
            lines.append(f"      result_id={failure.get('result_id')}")
            lines.append(f"      url={failure.get('url')}")
            if failure.get("mismatched_excerpts"):
                lines.append(f"      mismatched_excerpts={failure['mismatched_excerpts']}")
            if failure.get("verification_reason"):
                lines.append(f"      verification_reason={failure['verification_reason']}")
            if failure.get("source_content"):
                lines.append(f"      source_content={failure['source_content']}")

    if report["verified_evidence"]:
        lines.append("Verified evidence:")
        for index, evidence in enumerate(report["verified_evidence"], start=1):
            lines.append(f"  [{index}] {evidence.get('claim')}")

    return "\n".join(lines)


def format_batch_summary(summary: dict[str, Any]) -> str:
    lines = [
        "=== Batch Summary ===",
        f"Total runs: {summary['total_runs']}",
        f"Successful runs: {summary['successful_runs']}",
        f"Error runs: {summary['error_runs']}",
    ]

    if summary["sufficient_rate"] is not None:
        lines.append(
            f"Sufficient rate: {summary['sufficient_rate']:.1%} "
            f"({summary['sufficient_count']}/{summary['successful_runs']})"
        )

    lines.extend([
        f"Evidence total: {summary['evidence_total']}",
        f"Verified total: {summary['verified_total']}",
        f"Failed total: {summary['failed_total']}",
    ])

    if summary["verify_success_rate"] is not None:
        lines.append(f"Verify success rate: {summary['verify_success_rate']:.1%}")

    if summary.get("average_tool_call_count") is not None:
        lines.append(
            f"Average tool call count: {summary['average_tool_call_count']:.1f}"
        )

    if summary["failure_reason_counts"]:
        lines.append("Failure reason distribution:")
        for reason, count in summary["failure_reason_counts"].items():
            rate = summary["failure_reason_rates"].get(reason)
            rate_text = f"{rate:.1%}" if rate is not None else "n/a"
            lines.append(f"  - {reason}: {count} ({rate_text})")

    if summary["check_stage_counts"]:
        lines.append("Check stage distribution:")
        for stage, count in summary["check_stage_counts"].items():
            rate = summary["check_stage_rates"].get(stage)
            rate_text = f"{rate:.1%}" if rate is not None else "n/a"
            lines.append(f"  - {stage}: {count} ({rate_text})")

    if summary["errors"]:
        lines.append("Errors:")
        for error in summary["errors"]:
            lines.append(
                f"  - {error['company']}: {error['error_type']} - {error['error_message']}"
            )

    return "\n".join(lines)


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _format_rate(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _format_average(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def _render_distribution_rows(
    counts: dict[str, int],
    rates: dict[str, float | None],
) -> str:
    if not counts:
        return "<tr><td colspan='3'>None</td></tr>"

    return "".join(
        (
            "<tr>"
            f"<td>{_escape(reason)}</td>"
            f"<td>{count}</td>"
            f"<td>{_format_rate(rates.get(reason))}</td>"
            "</tr>"
        )
        for reason, count in counts.items()
    )


def _render_excerpt_list(excerpts: list[str]) -> str:
    if not excerpts:
        return "<em>None</em>"
    return "<ul>" + "".join(f"<li><code>{_escape(item)}</code></li>" for item in excerpts) + "</ul>"


def _render_source_content_block(content: str, *, label: str = "Source content") -> str:
    if not content:
        return f"<div><strong>{_escape(label)}:</strong> <em>Not available</em></div>"
    return (
        f"<div><strong>{_escape(label)}:</strong>"
        f"<pre class='source-content'>{_escape(content)}</pre></div>"
    )


def _render_evidence_card(
    evidence: dict[str, Any],
    *,
    card_class: str,
    extra_fields: str = "",
) -> str:
    return (
        f"<div class='card {card_class}'>"
        f"<div><strong>Claim:</strong> {_escape(evidence.get('claim'))}</div>"
        f"<div><strong>Result ID:</strong> <code>{_escape(evidence.get('result_id'))}</code></div>"
        f"<div><strong>URL:</strong> <a href='{_escape(evidence.get('url'))}' target='_blank' rel='noopener noreferrer'>{_escape(evidence.get('url'))}</a></div>"
        f"<div><strong>Reason:</strong> {_escape(evidence.get('reason'))}</div>"
        f"<div><strong>Source excerpts:</strong>{_render_excerpt_list(evidence.get('source_excerpts') or [])}</div>"
        f"{_render_source_content_block(evidence.get('source_content') or '')}"
        f"{extra_fields}"
        "</div>"
    )


def _render_run_report_html(report: dict[str, Any]) -> str:
    sufficient = report["sufficient"]
    sufficient_class = (
        "badge-yes" if sufficient is True else "badge-no" if sufficient is False else "badge-unknown"
    )
    sufficient_text = (
        "Yes" if sufficient is True else "No" if sufficient is False else "Unknown"
    )

    candidate_items = "".join(
        _render_evidence_card(evidence, card_class="candidate")
        for evidence in report.get("candidate_evidence") or []
    ) or "<p class='muted'>No candidate evidence.</p>"

    verified_items = "".join(
        _render_evidence_card(evidence, card_class="success")
        for evidence in report["verified_evidence"]
    ) or "<p class='muted'>No verified evidence.</p>"

    failed_items = "".join(
        (
            f"<div class='card failure'>"
            f"<div><strong>Stage:</strong> {_escape(_format_check_stage(failure.get('check_stage')))}</div>"
            f"<div><strong>Failure reason:</strong> {_escape(_format_failure_reason(failure.get('failure_reason')))}</div>"
            f"<div><strong>Claim:</strong> {_escape(failure.get('claim'))}</div>"
            f"<div><strong>Result ID:</strong> <code>{_escape(failure.get('result_id'))}</code></div>"
            f"<div><strong>URL:</strong> <a href='{_escape(failure.get('url'))}' target='_blank' rel='noopener noreferrer'>{_escape(failure.get('url'))}</a></div>"
            f"<div><strong>Reason:</strong> {_escape(failure.get('reason'))}</div>"
            f"<div><strong>Source excerpts:</strong>{_render_excerpt_list(failure.get('source_excerpts') or [])}</div>"
            f"<div><strong>Mismatched excerpts:</strong>{_render_excerpt_list(failure.get('mismatched_excerpts') or [])}</div>"
            f"<div><strong>Verification reason:</strong> {_escape(failure.get('verification_reason'))}</div>"
            f"{_render_source_content_block(failure.get('source_content') or '')}"
            "</div>"
        )
        for failure in report["failed_evidence_checks"]
    ) or "<p class='muted'>No failed evidence checks.</p>"

    return f"""
<section class="run-report">
  <h2>{_escape(report.get('company'))}</h2>
  <p class="muted">{_escape(report.get('requirement'))}</p>
  <div class="metrics">
    <div class="metric"><span>Sufficient</span><strong class="{sufficient_class}">{sufficient_text}</strong></div>
    <div class="metric"><span>Search tool calls</span><strong>{report.get('search_tool_call_count', 0)}</strong></div>
    <div class="metric"><span>Evidence total</span><strong>{report.get('evidence_total', 0)}</strong></div>
    <div class="metric"><span>Verified</span><strong>{report.get('verified_count', 0)}</strong></div>
    <div class="metric"><span>Failed</span><strong>{report.get('failed_count', 0)}</strong></div>
    <div class="metric"><span>Verify success rate</span><strong>{_format_rate(report.get('verify_success_rate'))}</strong></div>
  </div>
  <h3>Candidate Evidence</h3>
  {candidate_items}
  <h3>Verified Evidence</h3>
  {verified_items}
  <h3>Failed Evidence Checks</h3>
  {failed_items}
</section>
"""


def render_batch_summary_html(summary: dict[str, Any], *, title: str = "Research Batch Report") -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    run_sections = "".join(_render_run_report_html(report) for report in summary["runs"])

    error_section = ""
    if summary["errors"]:
        error_rows = "".join(
            (
                "<tr>"
                f"<td>{_escape(error.get('company'))}</td>"
                f"<td>{_escape(error.get('error_type'))}</td>"
                f"<td>{_escape(error.get('error_message'))}</td>"
                "</tr>"
            )
            for error in summary["errors"]
        )
        error_section = f"""
<h2>Errors</h2>
<table>
  <thead><tr><th>Company</th><th>Error Type</th><th>Message</th></tr></thead>
  <tbody>{error_rows}</tbody>
</table>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --border: #e5e7eb;
      --success: #047857;
      --failure: #b91c1c;
      --unknown: #92400e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: var(--muted); }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 20px 0 28px;
    }}
    .metric, .card, table {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
    }}
    .metric {{
      padding: 14px 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .metric strong {{
      font-size: 22px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      margin: 12px 0 24px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f9fafb;
      font-size: 13px;
      color: var(--muted);
    }}
    .run-report {{
      margin-top: 28px;
      padding-top: 8px;
      border-top: 2px solid var(--border);
    }}
    .run-report .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin: 16px 0 20px;
    }}
    .card {{
      padding: 14px 16px;
      margin-bottom: 12px;
    }}
    .card.success {{ border-left: 4px solid var(--success); }}
    .card.failure {{ border-left: 4px solid var(--failure); }}
    .card.candidate {{ border-left: 4px solid #2563eb; }}
    .badge-yes {{ color: var(--success); }}
    .badge-no {{ color: var(--failure); }}
    .badge-unknown {{ color: var(--unknown); }}
    code {{
      background: #f3f4f6;
      padding: 2px 4px;
      border-radius: 4px;
      word-break: break-word;
    }}
    ul {{
      margin: 8px 0 0;
      padding-left: 20px;
    }}
    pre.source-content {{
      margin: 8px 0 0;
      padding: 12px;
      background: #f9fafb;
      border: 1px solid var(--border);
      border-radius: 8px;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 320px;
      overflow: auto;
      font-size: 13px;
    }}
    a {{ color: #2563eb; }}
  </style>
</head>
<body>
  <main>
    <h1>{_escape(title)}</h1>
    <p class="muted">Generated at {generated_at}</p>

    <div class="summary-grid">
      <div class="metric"><span>Total runs</span><strong>{summary.get('total_runs', 0)}</strong></div>
      <div class="metric"><span>Successful runs</span><strong>{summary.get('successful_runs', 0)}</strong></div>
      <div class="metric"><span>Error runs</span><strong>{summary.get('error_runs', 0)}</strong></div>
      <div class="metric"><span>Sufficient rate</span><strong>{_format_rate(summary.get('sufficient_rate'))}</strong></div>
      <div class="metric"><span>Evidence total</span><strong>{summary.get('evidence_total', 0)}</strong></div>
      <div class="metric"><span>Verified total</span><strong>{summary.get('verified_total', 0)}</strong></div>
      <div class="metric"><span>Failed total</span><strong>{summary.get('failed_total', 0)}</strong></div>
      <div class="metric"><span>Verify success rate</span><strong>{_format_rate(summary.get('verify_success_rate'))}</strong></div>
      <div class="metric"><span>Average tool call count</span><strong>{_format_average(summary.get('average_tool_call_count'))}</strong></div>
    </div>

    <h2>Failure Reason Distribution</h2>
    <table>
      <thead><tr><th>Reason</th><th>Count</th><th>Rate of failures</th></tr></thead>
      <tbody>
        {_render_distribution_rows(summary.get('failure_reason_counts', {}), summary.get('failure_reason_rates', {}))}
      </tbody>
    </table>

    <h2>Check Stage Distribution</h2>
    <table>
      <thead><tr><th>Stage</th><th>Count</th><th>Rate of failures</th></tr></thead>
      <tbody>
        {_render_distribution_rows(summary.get('check_stage_counts', {}), summary.get('check_stage_rates', {}))}
      </tbody>
    </table>

    {error_section}

    <h2>Run Details</h2>
    {run_sections}
  </main>
</body>
</html>
"""


def export_batch_summary_html(
    summary: dict[str, Any],
    output_path: str | Path,
    *,
    title: str = "Research Batch Report",
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_batch_summary_html(summary, title=title),
        encoding="utf-8",
    )
    return path
