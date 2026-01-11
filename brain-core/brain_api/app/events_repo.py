import sqlite3


def insert_event(conn: sqlite3.Connection, ts_str: str, module: str, event_type: str, payload_str: str) -> None:
    conn.execute(
        """
        INSERT INTO events (ts, module, type, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (ts_str, module, event_type, payload_str),
    )
