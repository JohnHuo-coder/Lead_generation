from __future__ import annotations

from typing import Any

from db.db import pool


def _upsert_find_contact_status(
    place_id: str,
    config_id: str,
    *,
    apollo_status: str | None = None,
    anymail_finder_status: str | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> int:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prospect_discover.find_contact_status (
                    config_id,
                    place_id,
                    apollo_status,
                    anymail_finder_status,
                    status,
                    reason
                ) VALUES (
                    %(config_id)s,
                    %(place_id)s,
                    %(apollo_status)s,
                    %(anymail_finder_status)s,
                    %(status)s,
                    %(reason)s
                )
                ON CONFLICT (place_id, config_id)
                DO UPDATE SET
                    apollo_status = COALESCE(EXCLUDED.apollo_status, find_contact_status.apollo_status),
                    anymail_finder_status = COALESCE(
                        EXCLUDED.anymail_finder_status,
                        find_contact_status.anymail_finder_status
                    ),
                    status = COALESCE(EXCLUDED.status, find_contact_status.status),
                    reason = COALESCE(EXCLUDED.reason, find_contact_status.reason)
                RETURNING id;
                """,
                {
                    "place_id": place_id,
                    "config_id": config_id,
                    "apollo_status": apollo_status,
                    "anymail_finder_status": anymail_finder_status,
                    "status": status,
                    "reason": reason,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Failed to upsert find_contact_status row.")
            return row["id"]


def update_apollo_status(place_id: str, config_id: str, apollo_status: str) -> int:
    return _upsert_find_contact_status(
        place_id,
        config_id,
        apollo_status=apollo_status,
    )


def update_anymail_finder_status(
    place_id: str,
    config_id: str,
    anymail_finder_status: str,
) -> int:
    return _upsert_find_contact_status(
        place_id,
        config_id,
        anymail_finder_status=anymail_finder_status,
    )


def update_overall_status(
    place_id: str,
    config_id: str,
    status: str,
    reason: str,
) -> int:
    return _upsert_find_contact_status(
        place_id,
        config_id,
        status=status,
        reason=reason,
    )


def save_email_contact(
    place_id: str,
    config_id: str,
    email: str,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    full_name: str | None = None,
    job_title: str | None = None,
    source: str,
    apollo_id: str | None = None,
    linkedin_url: str | None = None,
) -> int:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prospect_discover.email_contact (
                    config_id,
                    place_id,
                    email,
                    first_name,
                    last_name,
                    full_name,
                    job_title,
                    "from",
                    apollo_id,
                    linkedin_url
                ) VALUES (
                    %(config_id)s,
                    %(place_id)s,
                    %(email)s,
                    %(first_name)s,
                    %(last_name)s,
                    %(full_name)s,
                    %(job_title)s,
                    %(source)s,
                    %(apollo_id)s,
                    %(linkedin_url)s
                )
                ON CONFLICT (place_id, email, config_id)
                DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    full_name = EXCLUDED.full_name,
                    job_title = EXCLUDED.job_title,
                    "from" = EXCLUDED."from",
                    apollo_id = COALESCE(EXCLUDED.apollo_id, email_contact.apollo_id),
                    linkedin_url = COALESCE(EXCLUDED.linkedin_url, email_contact.linkedin_url)
                RETURNING id;
                """,
                {
                    "config_id": config_id,
                    "place_id": place_id,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "job_title": job_title,
                    "source": source,
                    "apollo_id": apollo_id,
                    "linkedin_url": linkedin_url,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Failed to upsert email_contact row.")
            return row["id"]


def save_apollo_contact(
    place_id: str,
    config_id: str,
    email: str,
    person: dict[str, Any],
) -> int:
    return save_email_contact(
        place_id,
        config_id,
        email,
        first_name=person.get("first_name"),
        last_name=person.get("last_name"),
        full_name=person.get("name"),
        job_title=person.get("title"),
        source="apollo",
        apollo_id=person.get("id"),
        linkedin_url=person.get("linkedin_url"),
    )


def save_anymail_contact(
    place_id: str,
    config_id: str,
    email: str,
    first_name: str | None,
    last_name: str | None,
    full_name: str | None,
    job_title: str | None,
    linkedin_url: str | None = None,
) -> int:
    return save_email_contact(
        place_id,
        config_id,
        email,
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        job_title=job_title,
        source="anymail_finder",
        linkedin_url=linkedin_url,
    )
