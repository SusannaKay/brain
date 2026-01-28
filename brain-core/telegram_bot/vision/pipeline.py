import hashlib
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Union
from zoneinfo import ZoneInfo

from . import dao


def process_telegram_media(
    chat_id: int,
    message_id: int,
    media_bytes_or_path: Union[bytes, bytearray, memoryview, str, os.PathLike],
    media_type: str,
    media_mime: Optional[str],
    *,
    db_path: str,
    temp_dir: Optional[Union[str, os.PathLike]] = None,
) -> List[int]:
    trace_id = uuid.uuid4().hex
    base_dir = Path(temp_dir) if temp_dir else Path("/tmp")
    temp_path = base_dir / f"vision_{trace_id}"
    job_id: Optional[int] = None

    try:
        _write_temp_file(temp_path, media_bytes_or_path)
        sha256 = _sha256_file(temp_path)
        created_at = _utcnow_iso()

        job_id = dao.create_vision_job(
            created_at=created_at,
            status="RECEIVED",
            source_platform="telegram",
            chat_id=str(chat_id),
            message_id=str(message_id),
            media_type=media_type,
            media_mime=media_mime,
            sha256=sha256,
            trace_id=trace_id,
            db_path=db_path,
        )
        existing = dao.list_signal_ids_for_job(job_id, db_path=db_path)
        if existing:
            return existing

        dao.insert_extraction(
            job_id=job_id,
            model="dummy",
            raw_text="dummy",
            json_payload={"dummy": True},
            confidence_overall=0.5,
            trace_id=trace_id,
            db_path=db_path,
        )

        payload = _build_dummy_event_payload()
        signal_id = dao.insert_signal(
            job_id=job_id,
            signal_type="event_candidate.v1",
            confidence=0.80,
            payload_json=payload,
            proposed_action="create_calendar_event",
            action_status="PROPOSED",
            trace_id=trace_id,
            db_path=db_path,
        )
        dao.update_vision_job_status(job_id, "PARSED", db_path=db_path)
        return [signal_id]
    except Exception as exc:
        if job_id is not None:
            dao.update_vision_job_status(
                job_id,
                "FAILED",
                error_code="PIPELINE_ERROR",
                error_detail=str(exc)[:500],
                db_path=db_path,
            )
        raise
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _write_temp_file(path: Path, media_bytes_or_path: Union[bytes, bytearray, memoryview, str, os.PathLike]) -> None:
    if isinstance(media_bytes_or_path, (bytes, bytearray, memoryview)):
        path.write_bytes(bytes(media_bytes_or_path))
        return
    source_path = Path(media_bytes_or_path)
    data = source_path.read_bytes()
    path.write_bytes(data)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_dummy_event_payload() -> dict:
    tz = ZoneInfo("Europe/Rome")
    start_dt = datetime.now(tz) + timedelta(hours=1)
    return {
        "title": "Evento da confermare",
        "start": start_dt.replace(second=0, microsecond=0).isoformat(),
        "timezone": "Europe/Rome",
        "location_text": "",
        "notes": "",
        "source_hint": "other",
        "place_hint": "",
    }


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
