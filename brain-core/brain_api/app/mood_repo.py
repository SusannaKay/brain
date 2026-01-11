import sqlite3
from typing import Any, Dict, List, Optional, Tuple


def mood_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "ts_utc": row["ts_utc"],
        "local_date": row["local_date"],
        "slot": row["slot"],
        "energy_level": row["energy_level"],
        "mood_score": row["mood_score"],
        "mood_text": row["mood_text"],
        "did_thing": row["did_thing"],
        "waste_spend": row["waste_spend"],
        "created_at": row["created_at"],
    }


def insert_checkin(
    conn: sqlite3.Connection,
    ts_str: str,
    local_date: str,
    slot: str,
    energy_level: int,
    mood_score: int,
    mood_text: Optional[str],
    did_thing: Optional[str],
    waste_spend: bool,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO mood_checkins
            (ts_utc, local_date, slot, energy_level, mood_score, mood_text, did_thing, waste_spend, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_str,
            local_date,
            slot,
            energy_level,
            mood_score,
            mood_text,
            did_thing,
            1 if waste_spend else 0,
            created_at,
        ),
    )


def get_last(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, ts_utc, local_date, slot, energy_level, mood_score, mood_text, did_thing, waste_spend, created_at
        FROM mood_checkins
        ORDER BY ts_utc DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return mood_row_to_dict(row) if row else None


def get_week(conn: sqlite3.Connection, start_date: str) -> Tuple[List[sqlite3.Row], sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT id, ts_utc, local_date, slot, energy_level, mood_score, mood_text, did_thing, waste_spend, created_at
        FROM mood_checkins
        WHERE local_date >= ?
        ORDER BY local_date ASC, ts_utc ASC, id ASC
        """,
        (start_date,),
    ).fetchall()
    aggregates_row = conn.execute(
        """
        SELECT COUNT(*) AS count,
               AVG(mood_score) AS avg_mood_score,
               AVG(energy_level) AS avg_energy_level,
               SUM(waste_spend) AS waste_spend_count
        FROM mood_checkins
        WHERE local_date >= ?
        """,
        (start_date,),
    ).fetchone()
    return rows, aggregates_row
