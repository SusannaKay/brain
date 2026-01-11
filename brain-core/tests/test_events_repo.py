from __future__ import annotations

from brain_api.app import events_repo


def test_insert_event_persists_row(db_conn) -> None:
    events_repo.insert_event(
        db_conn,
        ts_str="2026-01-10T10:00:00+00:00",
        module="finance",
        event_type="expense_created",
        payload_str='{"amount": 1}',
    )
    db_conn.commit()

    row = db_conn.execute(
        """
        SELECT ts, module, type, payload_json
        FROM events
        """
    ).fetchone()
    assert row is not None
    assert row["ts"] == "2026-01-10T10:00:00+00:00"
    assert row["module"] == "finance"
    assert row["type"] == "expense_created"
    assert row["payload_json"] == '{"amount": 1}'
