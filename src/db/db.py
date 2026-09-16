from dotenv import load_dotenv
import os
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

load_dotenv()

pool = ConnectionPool(
    conninfo=(
        f"host={os.getenv('DB_HOST')}"
        f" port={os.getenv('DB_PORT')}"
        f" dbname={os.getenv('DB_NAME')}"
        f" user={os.getenv('DB_USER')}"
        f" password={os.getenv('DB_PASSWORD')}"
        f" sslmode=require"
    ),
    kwargs={
        "row_factory": dict_row,
        "prepare_threshold": None,  # Supabase transaction pooler 需要
    },
    min_size=1,
    max_size=10,
)