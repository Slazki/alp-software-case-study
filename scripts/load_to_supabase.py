from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience
    load_dotenv = None

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - startup guidance
    raise SystemExit(
        "Missing dependency: install requirements with `python -m pip install -r requirements.txt`."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = ROOT / "supabase" / "reset_and_seed.sql"


def main() -> None:
    if load_dotenv:
        load_dotenv(ROOT / ".env")

    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit(
            "SUPABASE_DB_URL is not set. Copy .env.example to .env and add the Supabase Postgres URI."
        )

    sql = SQL_FILE.read_text(encoding="utf-8")
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print(f"Loaded schema and cleaned seed data from {SQL_FILE}")


if __name__ == "__main__":
    main()
