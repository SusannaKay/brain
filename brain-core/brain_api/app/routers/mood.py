import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import mood_repo
from ..auth import verify_brain_token
from ..deps import get_db
from ..models import MoodCheckinIn
from ..settings import Settings, get_settings
from ..utils import _parse_ts, iso_utc, normalize_text
from zoneinfo import ZoneInfo

router = APIRouter()


@router.post("/mood/checkin", dependencies=[Depends(verify_brain_token)])
def mood_checkin(
    checkin: MoodCheckinIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    ts_str = iso_utc(_parse_ts(checkin.ts))
    local_date = normalize_text(checkin.local_date)
    slot = normalize_text(checkin.slot)
    if not local_date or not slot:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="local_date and slot are required")
    mood_text = normalize_text(checkin.mood_text) or None
    did_thing = normalize_text(checkin.did_thing) or None
    created_at = iso_utc()
    mood_repo.insert_checkin(
        conn,
        ts_str,
        local_date,
        slot,
        checkin.energy_level,
        checkin.mood_score,
        mood_text,
        did_thing,
        checkin.waste_spend,
        created_at,
    )
    conn.commit()
    return {
        "ts": ts_str,
        "local_date": local_date,
        "slot": slot,
        "energy_level": checkin.energy_level,
        "mood_score": checkin.mood_score,
        "mood_text": mood_text,
        "did_thing": did_thing,
        "waste_spend": checkin.waste_spend,
        "created_at": created_at,
    }


@router.get("/mood/last", dependencies=[Depends(verify_brain_token)])
def mood_last(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    data = mood_repo.get_last(conn)
    return {"ok": True, "data": data}


@router.get("/mood/week", dependencies=[Depends(verify_brain_token)])
def mood_week(
    days: int = Query(7, ge=1, le=30),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    tz = ZoneInfo(settings.timezone)
    now_tz = datetime.now(tz)
    start_date = (now_tz.date() - timedelta(days=days - 1)).isoformat()
    rows, aggregates_row = mood_repo.get_week(conn, start_date)
    aggregates = {
        "count": int(aggregates_row["count"] or 0),
        "avg_mood_score": float(aggregates_row["avg_mood_score"])
        if aggregates_row["avg_mood_score"] is not None
        else None,
        "avg_energy_level": float(aggregates_row["avg_energy_level"])
        if aggregates_row["avg_energy_level"] is not None
        else None,
        "waste_spend_count": int(aggregates_row["waste_spend_count"] or 0),
    }
    return {"items": [mood_repo.mood_row_to_dict(row) for row in rows], "aggregates": aggregates}
