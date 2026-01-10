import logging
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Union

import json
import sqlite3
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status

from .auth import verify_brain_token, verify_telegram_key
from .db import get_connection, init_db
from .models import BulkExpense, EventIn, ExpenseIn, ExpenseRecord, ExpenseSummary, MoodCheckinIn
from .settings import Settings, get_settings
from zoneinfo import ZoneInfo

app = FastAPI(title="Brain API", version="1.0.0")
logger = logging.getLogger("brain-api")

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time_module.perf_counter()
    logger.info(
        "request start method=%s path=%s client=%s",
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown",
    )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request error method=%s path=%s", request.method, request.url.path)
        raise
    duration_ms = (time_module.perf_counter() - start) * 1000
    logger.info(
        "request end method=%s path=%s status=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        getattr(response, "status_code", "unknown"),
        duration_ms,
    )
    return response


def amount_to_cents(amount: float) -> int:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid amount")
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def normalize_text(value: Optional[str]) -> str:
    return value.strip() if value and value.strip() else ""


def normalize_category(value: Optional[str]) -> str:
    return normalize_text(value)


def iso_utc(dt: Optional[datetime] = None) -> str:
    target = dt or datetime.now(timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    else:
        target = target.astimezone(timezone.utc)
    return target.isoformat()


def _parse_ts(value: Optional[Union[str, date, datetime]], allow_empty: bool = False) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            if allow_empty:
                return None
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ts cannot be empty",
            )
        normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid ts format; use ISO8601 datetime or YYYY-MM-DD date",
            )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid ts type; use ISO8601 datetime or YYYY-MM-DD date",
    )


def _parse_since(raw_since: str) -> datetime:
    value = raw_since.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since query parameter cannot be empty",
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid since format; use ISO8601 timestamp or YYYY-MM-DD date",
        )


def get_db(settings: Settings = Depends(get_settings)):
    yield from get_connection(settings.db_path)


@app.on_event("startup")
def on_startup() -> None:
    settings = get_settings()
    init_db(settings.db_path)


@app.get("/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.post("/finance/expense", dependencies=[Depends(verify_brain_token)])
def create_expense(
    expense: ExpenseIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    return _save_expense(conn, expense, source="api")


@app.post("/finance/expense/telegram", dependencies=[Depends(verify_telegram_key)])
def create_expense_telegram(
    expense: ExpenseIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    return _save_expense(conn, expense, source="telegram")


def _save_expense(conn: sqlite3.Connection, expense: ExpenseIn, source: str) -> Dict[str, Any]:
    cents = amount_to_cents(expense.amount)
    ts_str = iso_utc(_parse_ts(expense.ts, allow_empty=True))
    note = normalize_text(expense.note)
    category = normalize_category(expense.category)
    conn.execute(
        """
        INSERT OR IGNORE INTO finance_expenses (ts, amount_cents, note, category, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (ts_str, cents, note, category, source),
    )
    conn.commit()
    return {
        "ts": ts_str,
        "amount": float(Decimal(cents) / 100),
        "note": note or None,
        "category": category or "uncategorized",
        "source": source,
    }


@app.get("/finance/summary", response_model=ExpenseSummary, dependencies=[Depends(verify_brain_token)])
def finance_summary(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExpenseSummary:
    tz = ZoneInfo(settings.timezone)
    now_tz = datetime.now(tz)
    start_day = datetime.combine(now_tz.date(), time.min, tzinfo=tz)
    end_day = datetime.combine(now_tz.date(), time.max, tzinfo=tz)
    start_month = datetime(now_tz.year, now_tz.month, 1, tzinfo=tz)

    today_total_cents = _sum_between(conn, start_day, end_day)
    month_total_cents = _sum_between(conn, start_month, end_day)

    categories_rows = conn.execute(
        """
        SELECT CASE WHEN category = '' OR category IS NULL THEN 'uncategorized' ELSE category END AS category,
               SUM(amount_cents) AS total
        FROM finance_expenses
        WHERE ts BETWEEN ? AND ?
        GROUP BY category
        ORDER BY total DESC
        """,
        (_as_utc(start_day), _as_utc(end_day)),
    ).fetchall()

    latest_rows = conn.execute(
        """
        SELECT ts, amount_cents, note,
               CASE WHEN category = '' OR category IS NULL THEN 'uncategorized' ELSE category END AS category,
               COALESCE(source, '') AS source
        FROM finance_expenses
        ORDER BY ts DESC
        LIMIT 10
        """
    ).fetchall()

    return ExpenseSummary(
        today_date=now_tz.date().isoformat(),
        today_total=_cents_to_float(today_total_cents),
        month=f"{now_tz.year:04d}-{now_tz.month:02d}",
        month_total=_cents_to_float(month_total_cents),
        top_categories=[{"category": row[0], "total": _cents_to_float(row[1] or 0)} for row in categories_rows],
        latest=[
            ExpenseRecord(
                ts=row[0],
                amount=_cents_to_float(row[1] or 0),
                note=row[2] or None,
                category=row[3],
                source=row[4],
            )
            for row in latest_rows
        ],
    )


@app.post("/finance/bulk_import", dependencies=[Depends(verify_brain_token)])
def finance_bulk_import(
    expenses: List[BulkExpense],
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    inserted = 0
    for item in expenses:
        cents = amount_to_cents(item.amount)
        ts_str = iso_utc(_parse_ts(item.ts))
        note = normalize_text(item.note)
        category = normalize_category(item.category)
        source = normalize_text(item.source) or "bulk"
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO finance_expenses (ts, amount_cents, note, category, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts_str, cents, note, category, source),
        )
        inserted += cursor.rowcount if cursor.rowcount is not None else 0
    conn.commit()
    return {"inserted": inserted, "received": len(expenses)}


@app.get("/finance/export", dependencies=[Depends(verify_brain_token)])
def finance_export(
    since: str = Query(..., description="ISO8601 timestamp or YYYY-MM-DD date"),
    conn: sqlite3.Connection = Depends(get_db),
) -> List[Dict[str, Any]]:
    since_iso = iso_utc(_parse_since(since))
    rows = conn.execute(
        """
        SELECT ts, amount_cents, note,
               CASE WHEN category = '' OR category IS NULL THEN 'uncategorized' ELSE category END AS category,
               COALESCE(source, '') AS source
        FROM finance_expenses
        WHERE ts >= ?
        ORDER BY ts ASC
        """,
        (since_iso,),
    ).fetchall()
    return [
        {
            "ts": row[0],
            "amount": _cents_to_float(row[1] or 0),
            "note": row[2] or None,
            "category": row[3],
            "source": row[4],
        }
        for row in rows
    ]


@app.post("/mood/checkin", dependencies=[Depends(verify_brain_token)])
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
            checkin.energy_level,
            checkin.mood_score,
            mood_text,
            did_thing,
            1 if checkin.waste_spend else 0,
            created_at,
        ),
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


def _mood_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
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


@app.get("/mood/last", dependencies=[Depends(verify_brain_token)])
def mood_last(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, ts_utc, local_date, slot, energy_level, mood_score, mood_text, did_thing, waste_spend, created_at
        FROM mood_checkins
        ORDER BY ts_utc DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return {"ok": True, "data": _mood_row_to_dict(row) if row else None}


@app.get("/mood/week", dependencies=[Depends(verify_brain_token)])
def mood_week(
    days: int = Query(7, ge=1, le=30),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    tz = ZoneInfo(settings.timezone)
    now_tz = datetime.now(tz)
    start_date = (now_tz.date() - timedelta(days=days - 1)).isoformat()
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
    return {"items": [_mood_row_to_dict(row) for row in rows], "aggregates": aggregates}


@app.post("/ingest", dependencies=[Depends(verify_brain_token)])
def ingest_event(
    event: EventIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    ts_str = iso_utc(event.ts)
    payload_str = json.dumps(event.payload_json, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO events (ts, module, type, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (ts_str, event.module, event.type, payload_str),
    )
    conn.commit()
    return {"ts": ts_str, "module": event.module, "type": event.type}


def _cents_to_float(value: int) -> float:
    return float(Decimal(value) / 100)


def _as_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _sum_between(conn: sqlite3.Connection, start: datetime, end: datetime) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount_cents), 0) FROM finance_expenses
        WHERE ts BETWEEN ? AND ?
        """,
        (_as_utc(start), _as_utc(end)),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0
