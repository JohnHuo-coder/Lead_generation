from __future__ import annotations

import logging
from typing import Any

from db.db import pool
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

_UPSERT_SQL = """
INSERT INTO research_run_results (
    run_id,
    user_id,
    place_id,
    company_name,
    requirement_id,
    sufficient,
    satisfied,
    verified_claims,
    sufficient_reason,
    error
)
VALUES (
    %(run_id)s,
    %(user_id)s,
    %(place_id)s,
    %(company_name)s,
    %(requirement_id)s,
    %(sufficient)s,
    %(satisfied)s,
    %(verified_claims)s,
    %(sufficient_reason)s,
    %(error)s
)
ON CONFLICT (run_id, company_name, requirement_id)
DO UPDATE SET
    place_id = EXCLUDED.place_id,
    user_id = EXCLUDED.user_id,
    sufficient = EXCLUDED.sufficient,
    satisfied = EXCLUDED.satisfied,
    verified_claims = EXCLUDED.verified_claims,
    sufficient_reason = EXCLUDED.sufficient_reason,
    error = EXCLUDED.error,
    updated_at = now()
"""


def upsert_research_pair_results(
    *,
    run_id: str,
    user_id: str,
    pair_results: list[dict[str, Any]],
) -> int:
    """Persist one row per (company, requirement). Returns rows written."""
    if not pair_results:
        return 0

    rows = [
        {
            "run_id": run_id,
            "user_id": user_id,
            "place_id": item.get("place_id") or "",
            "company_name": item.get("company") or "",
            "requirement_id": item.get("requirement_id") or "unknown",
            "sufficient": item.get("sufficient"),
            "satisfied": item.get("satisfied"),
            "verified_claims": Jsonb(item.get("verified_claims") or []),
            "sufficient_reason": item.get("sufficient_reason") or "",
            "error": item.get("error"),
        }
        for item in pair_results
    ]

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # psycopg3 executemany uses pipeline mode when available.
                cur.executemany(_UPSERT_SQL, rows)
            conn.commit()
    except Exception:
        logger.exception("Failed to upsert research_run_results for run %s", run_id)
        raise
    return len(rows)
