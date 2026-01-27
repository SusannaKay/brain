import json

from telegram_bot.vision import dao


def _db_path(conn) -> str:
    return conn.execute("PRAGMA database_list").fetchone()[2]


def _seed_signal(conn) -> int:
    db_path = _db_path(conn)
    job_id = dao.create_vision_job(
        created_at="2024-01-01T00:00:00Z",
        status="RECEIVED",
        source_platform="telegram",
        chat_id="1",
        message_id="1",
        media_type="photo",
        media_mime="image/jpeg",
        sha256="deadbeef",
        trace_id="trace",
        db_path=db_path,
        conn=conn,
    )
    signal_id = dao.insert_signal(
        job_id=job_id,
        signal_type="event_candidate.v1",
        confidence=0.8,
        payload_json={
            "title": "Vecchio titolo",
            "start": "2024-01-01T10:00:00+01:00",
            "timezone": "Europe/Rome",
            "location_text": "Roma",
        },
        proposed_action="create_calendar_event",
        action_status="PROPOSED",
        trace_id="trace",
        db_path=db_path,
        conn=conn,
    )
    return signal_id


def test_update_signal_payload_field(db_conn) -> None:
    db_path = _db_path(db_conn)
    signal_id = _seed_signal(db_conn)

    dao.update_signal_payload_field(
        signal_id,
        "title",
        "Nuovo titolo",
        db_path=db_path,
        conn=db_conn,
    )
    row = db_conn.execute("SELECT payload_json FROM vision_signals WHERE id = ?", (signal_id,)).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["title"] == "Nuovo titolo"

    dao.update_signal_payload_field(
        signal_id,
        "time",
        "09:30",
        db_path=db_path,
        conn=db_conn,
    )
    row = db_conn.execute("SELECT payload_json FROM vision_signals WHERE id = ?", (signal_id,)).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["start"].endswith("09:30:00+01:00")


def test_pending_edit_flow(db_conn) -> None:
    db_path = _db_path(db_conn)
    signal_id = _seed_signal(db_conn)

    dao.upsert_pending_edit(
        chat_id="123",
        signal_id=signal_id,
        field="title",
        db_path=db_path,
        conn=db_conn,
    )
    row = dao.get_pending_edit("123", db_path=db_path, conn=db_conn)
    assert row is not None
    assert row["field"] == "title"

    dao.upsert_pending_edit(
        chat_id="123",
        signal_id=signal_id,
        field="time",
        db_path=db_path,
        conn=db_conn,
    )
    row = dao.get_pending_edit("123", db_path=db_path, conn=db_conn)
    assert row is not None
    assert row["field"] == "time"

    dao.clear_pending_edit("123", db_path=db_path, conn=db_conn)
    assert dao.get_pending_edit("123", db_path=db_path, conn=db_conn) is None
