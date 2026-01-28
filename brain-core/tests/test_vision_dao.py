import json
from datetime import datetime

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
    parsed = datetime.fromisoformat(payload["start"])
    assert parsed.tzinfo is not None
    assert parsed.hour == 9 and parsed.minute == 30


def test_create_job_idempotent(db_conn) -> None:
    db_path = _db_path(db_conn)
    job_id_first = dao.create_vision_job(
        created_at="2024-01-01T00:00:00Z",
        status="RECEIVED",
        source_platform="telegram",
        chat_id="10",
        message_id="99",
        media_type="photo",
        media_mime="image/jpeg",
        sha256="deadbeef",
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    job_id_second = dao.create_vision_job(
        created_at="2024-01-01T00:00:00Z",
        status="RECEIVED",
        source_platform="telegram",
        chat_id="10",
        message_id="99",
        media_type="photo",
        media_mime="image/jpeg",
        sha256="deadbeef",
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    assert job_id_first == job_id_second
    count = db_conn.execute(
        "SELECT COUNT(*) as c FROM vision_jobs WHERE source_platform = ? AND chat_id = ? AND message_id = ?",
        ("telegram", "10", "99"),
    ).fetchone()["c"]
    assert count == 1


def test_fk_cascade_delete_job(db_conn) -> None:
    db_path = _db_path(db_conn)
    job_id = dao.create_vision_job(
        created_at="2024-01-01T00:00:00Z",
        status="RECEIVED",
        source_platform="telegram",
        chat_id="2",
        message_id="2",
        media_type="photo",
        media_mime="image/jpeg",
        sha256="deadbeef",
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    dao.insert_extraction(
        job_id=job_id,
        model="dummy",
        raw_text="raw",
        json_payload={"dummy": True},
        confidence_overall=0.5,
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    dao.insert_signal(
        job_id=job_id,
        signal_type="event_candidate.v1",
        confidence=0.5,
        payload_json={"title": "X"},
        proposed_action="create_calendar_event",
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    db_conn.execute("DELETE FROM vision_jobs WHERE id = ?", (job_id,))
    db_conn.commit()
    assert db_conn.execute("SELECT COUNT(*) as c FROM vision_extractions WHERE job_id = ?", (job_id,)).fetchone()["c"] == 0
    assert db_conn.execute("SELECT COUNT(*) as c FROM vision_signals WHERE job_id = ?", (job_id,)).fetchone()["c"] == 0


def test_raw_text_truncated(db_conn) -> None:
    db_path = _db_path(db_conn)
    job_id = dao.create_vision_job(
        created_at="2024-01-01T00:00:00Z",
        status="RECEIVED",
        source_platform="telegram",
        chat_id="3",
        message_id="3",
        media_type="photo",
        media_mime="image/jpeg",
        sha256="deadbeef",
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    long_text = "x" * (dao.MAX_RAW_TEXT_LEN + 100)
    dao.insert_extraction(
        job_id=job_id,
        model="dummy",
        raw_text=long_text,
        json_payload={"dummy": True},
        confidence_overall=0.5,
        trace_id="trace",
        db_path=db_path,
        conn=db_conn,
    )
    stored = db_conn.execute(
        "SELECT raw_text FROM vision_extractions WHERE job_id = ?",
        (job_id,),
    ).fetchone()["raw_text"]
    assert stored is not None
    assert len(stored) == dao.MAX_RAW_TEXT_LEN


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
