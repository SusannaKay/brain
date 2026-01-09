import sqlite3
from pathlib import Path
from typing import Generator


def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    data_dir = Path(db_path).parent
    data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS finance_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                note TEXT,
                category TEXT,
                source TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_expenses_unique
            ON finance_expenses (ts, amount_cents, note, category, source);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                module TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mood_checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                local_date TEXT NOT NULL,
                slot TEXT NOT NULL,
                energy_level INTEGER NOT NULL,
                mood_score INTEGER NOT NULL,
                mood_text TEXT,
                did_thing TEXT,
                waste_spend INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
