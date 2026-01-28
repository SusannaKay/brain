import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple



def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_vision_job(
    created_at: str,
    status: str,
    source_platform: str,
    chat_id: str,
    message_id: str,
    media_type: str,
    media_mime: Optional[str],
    sha256: str,
    trace_id: str,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO vision_jobs (
                created_at, status, source_platform, chat_id, message_id,
                media_type, media_mime, sha256, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                status,
                source_platform,
                chat_id,
                message_id,
                media_type,
                media_mime,
                sha256,
                trace_id,
            ),
        )
        row = conn.execute(
            """
            SELECT id FROM vision_jobs
            WHERE source_platform = ? AND chat_id = ? AND message_id = ?
            """,
            (source_platform, chat_id, message_id),
        ).fetchone()
        if not row:
            raise RuntimeError("Failed to create or fetch vision_job")
        conn.commit()
        return int(row["id"])
    finally:
        if owned_conn:
            conn.close()


def get_job_by_message(
    source_platform: str,
    chat_id: str,
    message_id: str,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[sqlite3.Row]:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    try:
        row = conn.execute(
            """
            SELECT * FROM vision_jobs
            WHERE source_platform = ? AND chat_id = ? AND message_id = ?
            """,
            (source_platform, chat_id, message_id),
        ).fetchone()
        return row
    finally:
        if owned_conn:
            conn.close()


def update_vision_job_status(
    job_id: int,
    status: str,
    error_code: Optional[str] = None,
    error_detail: Optional[str] = None,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    try:
        conn.execute(
            """
            UPDATE vision_jobs
            SET status = ?, error_code = ?, error_detail = ?
            WHERE id = ?
            """,
            (status, error_code, error_detail, job_id),
        )
        conn.commit()
    finally:
        if owned_conn:
            conn.close()


def insert_extraction(
    job_id: int,
    model: str,
    raw_text: Optional[str],
    json_payload: Dict[str, Any],
    confidence_overall: float,
    *,
    trace_id: str,
    created_at: Optional[str] = None,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    created_at = created_at or _utcnow_iso()
    try:
        cursor = conn.execute(
            """
            INSERT INTO vision_extractions (
                job_id, created_at, model, raw_text, json_payload, confidence_overall, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                created_at,
                model,
                raw_text,
                json.dumps(json_payload, ensure_ascii=False),
                confidence_overall,
                trace_id,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        if owned_conn:
            conn.close()


def insert_signal(
    job_id: int,
    signal_type: str,
    confidence: float,
    payload_json: Dict[str, Any],
    proposed_action: str,
    action_status: str = "PROPOSED",
    *,
    trace_id: str,
    created_at: Optional[str] = None,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    created_at = created_at or _utcnow_iso()
    try:
        cursor = conn.execute(
            """
            INSERT INTO vision_signals (
                job_id, created_at, signal_type, confidence, payload_json,
                proposed_action, action_status, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                created_at,
                signal_type,
                confidence,
                json.dumps(payload_json, ensure_ascii=False),
                proposed_action,
                action_status,
                trace_id,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        if owned_conn:
            conn.close()


def list_signal_ids_for_job(
    job_id: int,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> List[int]:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    try:
        rows = conn.execute(
            "SELECT id FROM vision_signals WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        if owned_conn:
            conn.close()


def get_signal(
    signal_id: int,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[sqlite3.Row]:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    try:
        row = conn.execute(
            "SELECT * FROM vision_signals WHERE id = ?",
            (signal_id,),
        ).fetchone()
        return row
    finally:
        if owned_conn:
            conn.close()


def update_signal_status(
    signal_id: int,
    action_status: str,
    action_error: Optional[str] = None,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    updated_at = _utcnow_iso()
    try:
        conn.execute(
            """
            UPDATE vision_signals
            SET action_status = ?, action_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (action_status, action_error, updated_at, signal_id),
        )
        conn.commit()
    finally:
        if owned_conn:
            conn.close()


def update_signal_payload_field(
    signal_id: int,
    field: str,
    value: str,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    try:
        row = conn.execute(
            "SELECT payload_json FROM vision_signals WHERE id = ?",
            (signal_id,),
        ).fetchone()
        if not row:
            raise ValueError("Signal not found")
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        _apply_payload_update(payload, field, value)
        updated_at = _utcnow_iso()
        conn.execute(
            """
            UPDATE vision_signals
            SET payload_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), updated_at, signal_id),
        )
        conn.commit()
        return payload
    finally:
        if owned_conn:
            conn.close()


def upsert_pending_edit(
    chat_id: str,
    signal_id: int,
    field: str,
    *,
    created_at: Optional[str] = None,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    owned_conn = conn is None
    if owned_conn:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
    assert conn is not None
    created_at = created_at or _utcnow_iso()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO vision_pending_edits (chat_id, signal_id, field, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, signal_id, field, created_at),
        )
        conn.commit()
    finally:
        if owned_conn:
            conn.close()


def get_pending_edit(
    chat_id: str,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[sqlite3.Row]:
    owned_conn = conn is None
    if owned_conn:
        conn = next(get_connection(db_path))
    assert conn is not None
    try:
        row = conn.execute(
            "SELECT * FROM vision_pending_edits WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return row
    finally:
        if owned_conn:
            conn.close()


def clear_pending_edit(
    chat_id: str,
    *,
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    owned_conn = conn is None
    if owned_conn:
        conn = next(get_connection(db_path))
    assert conn is not None
    try:
        conn.execute("DELETE FROM vision_pending_edits WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        if owned_conn:
            conn.close()


def _apply_payload_update(payload: Dict[str, Any], field: str, value: str) -> None:
    if field == "title":
        payload["title"] = value
        return
    if field == "location":
        payload["location_text"] = value
        return
    if field == "time":
        payload["start"] = _update_start_time(payload.get("start"), value, payload.get("timezone"))
        return
    payload[field] = value


def _update_start_time(start_value: Optional[str], time_value: str, timezone_name: Optional[str]) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not time_value or ":" not in time_value:
        raise ValueError("Invalid time format")
    parts = time_value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Invalid time format")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Invalid time format")

    tz_name = timezone_name or "Europe/Rome"
    tz = ZoneInfo(tz_name)
    base_dt: Optional[datetime] = None
    if start_value:
        try:
            base_dt = datetime.fromisoformat(start_value)
        except ValueError:
            base_dt = None
    if base_dt is None:
        base_dt = datetime.now(tz)
    if base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=tz)

    updated = base_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return updated.isoformat()
