from db.db import pool


def _field(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def upsert_initial_candidates(item):
    with pool.connection as conn:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO initial_candidates (
                place_id,
                company_name,
                website,
                phone,
                distance_from_center,
                stars,
                description
            )
            VALUES (
                %(place_id)s,
                %(company_name)s,
                %(website)s,
                %(phone)s,
                %(distance_from_center)s,
                %(stars)s,
                %(description)s
            )
            ON CONFLICT (place_id)

            DO UPDATE SET
                company_name = EXCLUDED.company_name,
                website = EXCLUDED.website,
                phone = EXCLUDED.phone,
                distance_from_center = EXCLUDED.distance_from_center,
                stars = EXCLUDED.stars,
                description = EXCLUDED.description
            
            RETURNING id;

            """
            cur.execute(sql, {
                "place_id": _field(item, "place_id"),
                "company_name": _field(item, "company_name"),
                "website": _field(item, "website"),
                "phone": _field(item, "phone"),
                "distance_from_center": _field(item, "distance_from_center"),
                "stars": _field(item, "stars"),
                "description": _field(item, "description"),
            })

            return cur.fetchone()["id"]


