from __future__ import annotations

from brain_api.app import mood_repo


def test_insert_checkin_get_last(db_conn) -> None:
    mood_repo.insert_checkin(
        db_conn,
        ts_str="2026-01-10T10:00:00+00:00",
        local_date="2026-01-10",
        slot="evening",
        energy_level=1,
        mood_score=2,
        mood_text="ok",
        did_thing=None,
        waste_spend=False,
        created_at="2026-01-10T10:05:00+00:00",
    )
    mood_repo.insert_checkin(
        db_conn,
        ts_str="2026-01-10T12:00:00+00:00",
        local_date="2026-01-10",
        slot="evening",
        energy_level=0,
        mood_score=1,
        mood_text=None,
        did_thing="walk",
        waste_spend=True,
        created_at="2026-01-10T12:05:00+00:00",
    )
    db_conn.commit()

    last = mood_repo.get_last(db_conn)
    assert last is not None
    assert last["ts_utc"] == "2026-01-10T12:00:00+00:00"
    assert last["did_thing"] == "walk"


def test_get_week(db_conn) -> None:
    for ts_str, local_date, waste in [
        ("2026-01-10T10:00:00+00:00", "2026-01-10", True),
        ("2026-01-11T10:00:00+00:00", "2026-01-11", False),
        ("2026-01-12T10:00:00+00:00", "2026-01-12", True),
    ]:
        mood_repo.insert_checkin(
            db_conn,
            ts_str=ts_str,
            local_date=local_date,
            slot="evening",
            energy_level=1,
            mood_score=2,
            mood_text=None,
            did_thing=None,
            waste_spend=waste,
            created_at=ts_str,
        )
    db_conn.commit()

    rows, aggregates = mood_repo.get_week(db_conn, "2026-01-10")
    assert len(rows) == 3
    assert aggregates["count"] == 3
