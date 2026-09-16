from db.db import pool

def update_status(place_id, config_id, fallback_from, apollo_status):
    with pool.connection as conn:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO prospect_discover.find_contact_status (
                config_id,
                place_id,
                fallback_from,
                apollo_status
            ) VALUES (
                $1,  
                $2,  
                $3,  
                $4  
            )
            ON CONFLICT (place_id, config_id)
            DO UPDATE SET
                fallback_from = EXCLUDED.fallback_from,
                apollo_status = EXCLUDED.apollo_status;
            """
            cur.execute(sql, {
                "place_id": place_id,
                "config_id": config_id,
                "fallback_from": fallback_from,
                "apollo_status": apollo_status
            })

            return cur.fetchone()["id"]