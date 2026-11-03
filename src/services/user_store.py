from __future__ import annotations

import logging
import os
import threading
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv
from langgraph.store.base import BaseStore
from langgraph.store.postgres import PostgresStore
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

logger = logging.getLogger(__name__)

USER_PROFILE_KEY = "profile"
RUN_RECORD_KEY = "record"

_pool: ConnectionPool | None = None
_store: PostgresStore | None = None
_init_lock = threading.RLock()


def database_uri() -> str:
    """Build a Postgres URI from the same env vars as db.db.

    For Supabase, prefer the session pooler port for LangGraph Store if the
    transaction pooler misbehaves. sslmode is required. prepare_threshold is
    disabled on the pool (see _get_pool).
    """
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    dbname = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    missing = [
        name
        for name, value in [
            ("DB_HOST", host),
            ("DB_PORT", port),
            ("DB_NAME", dbname),
            ("DB_USER", user),
            ("DB_PASSWORD", password),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing Postgres env for LangGraph persistence: "
            + ", ".join(missing)
        )
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{dbname}?sslmode=require"
    )


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _init_lock:
        if _pool is not None:
            return _pool
        # prepare_threshold=None: required for Supabase transaction pooler.
        _pool = ConnectionPool(
            conninfo=database_uri(),
            min_size=1,
            max_size=10,
            kwargs={
                "autocommit": True,
                "prepare_threshold": None,
                "row_factory": dict_row,
            },
            open=True,
        )
        return _pool


def get_planner_store() -> PostgresStore:
    """Lazy Postgres store singleton (creates store tables on first use)."""
    global _store
    if _store is not None:
        return _store
    with _init_lock:
        if _store is not None:
            return _store
        store = PostgresStore(_get_pool())
        store.setup()
        _store = store
        logger.info("Initialized PostgresStore for planner/orchestrator state")
        return _store


# Back-compat alias resolved lazily via module __getattr__.
def __getattr__(name: str) -> Any:
    if name == "planner_store":
        return get_planner_store()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def current_store(preferred: BaseStore | None = None) -> BaseStore:
    """Return the process-wide Postgres store used by planner and orchestrator.

    ``preferred`` (e.g. ``runtime.store``) is ignored on purpose: langgraph-api
    may inject a different store into ToolRuntime, which previously caused
    planner writes to miss the Postgres rows that orchestrator reads.
    """
    return get_planner_store()


def user_namespace(user_id: str) -> tuple[str, str]:
    return ("user", user_id)


def run_namespace(run_id: str) -> tuple[str, str]:
    return ("run", run_id)


def get_user_id(config: dict | None) -> str:
    configurable = (config or {}).get("configurable") or {}
    user_id = configurable.get("user_id")
    if isinstance(user_id, str) and user_id.strip():
        return user_id.strip()
    return "default"


def get_profile(store: BaseStore | None, user_id: str) -> dict[str, Any]:
    if store is None:
        return {}
    item = store.get(user_namespace(user_id), USER_PROFILE_KEY)
    if item is None or not isinstance(item.value, dict):
        return {}
    return dict(item.value)


def put_profile(store: BaseStore | None, user_id: str, profile: dict[str, Any]) -> None:
    if store is None:
        return
    current = get_profile(store, user_id)
    current.update(profile)
    store.put(user_namespace(user_id), USER_PROFILE_KEY, current)


def get_run(store: BaseStore | None, run_id: str) -> dict[str, Any]:
    if store is None:
        return {}
    item = store.get(run_namespace(run_id), RUN_RECORD_KEY)
    if item is None or not isinstance(item.value, dict):
        return {}
    return dict(item.value)


def put_run(store: BaseStore | None, run_id: str, record: dict[str, Any]) -> None:
    if store is None:
        return
    current = get_run(store, run_id)
    current.update(record)
    store.put(run_namespace(run_id), RUN_RECORD_KEY, current)


def update_run_status(
    store: BaseStore | None,
    run_id: str,
    status: str,
    **extra: Any,
) -> None:
    payload = {"status": status, **extra}
    put_run(store, run_id, payload)
