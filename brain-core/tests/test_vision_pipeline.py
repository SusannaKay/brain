from pathlib import Path

import pytest

from datetime import datetime

from telegram_bot.vision import pipeline


def test_pipeline_temp_cleanup_on_error(tmp_path, monkeypatch) -> None:
    created_paths = []

    def fail_create_job(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline.dao, "create_vision_job", fail_create_job)

    try:
        pipeline.process_telegram_media(
            chat_id=1,
            message_id=1,
            media_bytes_or_path=b"hello",
            media_type="photo",
            media_mime="image/jpeg",
            db_path=str(tmp_path / "test.db"),
            temp_dir=tmp_path,
        )
    except RuntimeError:
        pass

    leftovers = list(Path(tmp_path).glob("vision_*"))
    assert leftovers == []


def test_dummy_payload_timezone() -> None:
    payload = pipeline._build_dummy_event_payload()
    assert payload["timezone"] == "Europe/Rome"
    parsed = datetime.fromisoformat(payload["start"])
    assert parsed.tzinfo is not None
