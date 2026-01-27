import sqlite3
from pathlib import Path
from typing import Generator


def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON;")
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
        conn.execute("PRAGMA foreign_keys=ON;")
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vision_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                source_platform TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                media_mime TEXT,
                sha256 TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                error_code TEXT,
                error_detail TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_vision_jobs_message_unique
            ON vision_jobs (source_platform, chat_id, message_id);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vision_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                model TEXT NOT NULL,
                raw_text TEXT,
                json_payload TEXT,
                confidence_overall REAL,
                trace_id TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES vision_jobs(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vision_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                payload_json TEXT NOT NULL,
                proposed_action TEXT NOT NULL,
                action_status TEXT NOT NULL,
                action_error TEXT,
                trace_id TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (job_id) REFERENCES vision_jobs(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS places_saved (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                signal_id INTEGER,
                place_provider TEXT NOT NULL,
                place_id TEXT NOT NULL,
                name TEXT,
                address TEXT,
                lat REAL,
                lng REAL,
                FOREIGN KEY (signal_id) REFERENCES vision_signals(id) ON DELETE SET NULL
            );
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_places_saved_unique
            ON places_saved (place_provider, place_id);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                signal_id INTEGER,
                calendar_provider TEXT NOT NULL,
                calendar_id TEXT,
                event_id TEXT NOT NULL,
                event_link TEXT,
                FOREIGN KEY (signal_id) REFERENCES vision_signals(id) ON DELETE SET NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens_google (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                subject TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                expiry_ts TEXT,
                scopes TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_oauth_tokens_google_subject
            ON oauth_tokens_google (subject);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vision_pending_edits (
                chat_id TEXT PRIMARY KEY,
                signal_id INTEGER NOT NULL,
                field TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES vision_signals(id) ON DELETE CASCADE
            );
            """
        )
