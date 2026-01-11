import json
import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from .. import events_repo
from ..auth import verify_brain_token
from ..deps import get_db
from ..models import EventIn
from ..utils import iso_utc

router = APIRouter()


@router.post("/ingest", dependencies=[Depends(verify_brain_token)])
def ingest_event(
    event: EventIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    ts_str = iso_utc(event.ts)
    payload_str = json.dumps(event.payload_json, ensure_ascii=False)
    events_repo.insert_event(conn, ts_str, event.module, event.type, payload_str)
    conn.commit()
    return {"ts": ts_str, "module": event.module, "type": event.type}
