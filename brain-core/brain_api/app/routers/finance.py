import sqlite3
from datetime import datetime, time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from .. import finance_repo
from ..auth import verify_brain_token, verify_telegram_key
from ..deps import get_db
from ..models import BulkExpense, ExpenseIn, ExpenseRecord, ExpenseSummary
from ..settings import Settings, get_settings
from ..utils import _as_utc, _cents_to_float, _parse_since, iso_utc
from zoneinfo import ZoneInfo

router = APIRouter()


@router.post("/finance/expense", dependencies=[Depends(verify_brain_token)])
def create_expense(
    expense: ExpenseIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    return finance_repo.save_expense(conn, expense, source="api")


@router.post("/finance/expense/telegram", dependencies=[Depends(verify_telegram_key)])
def create_expense_telegram(
    expense: ExpenseIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    return finance_repo.save_expense(conn, expense, source="telegram")


@router.get("/finance/summary", response_model=ExpenseSummary, dependencies=[Depends(verify_brain_token)])
def finance_summary(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExpenseSummary:
    tz = ZoneInfo(settings.timezone)
    now_tz = datetime.now(tz)
    start_day = datetime.combine(now_tz.date(), time.min, tzinfo=tz)
    end_day = datetime.combine(now_tz.date(), time.max, tzinfo=tz)
    start_month = datetime(now_tz.year, now_tz.month, 1, tzinfo=tz)

    today_total_cents = finance_repo.sum_between(conn, start_day, end_day)
    month_total_cents = finance_repo.sum_between(conn, start_month, end_day)

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


@router.post("/finance/bulk_import", dependencies=[Depends(verify_brain_token)])
def finance_bulk_import(
    expenses: List[BulkExpense],
    conn: sqlite3.Connection = Depends(get_db),
) -> Dict[str, Any]:
    inserted = finance_repo.bulk_insert(conn, expenses)
    conn.commit()
    return {"inserted": inserted, "received": len(expenses)}


@router.get("/finance/export", dependencies=[Depends(verify_brain_token)])
def finance_export(
    since: str = Query(..., description="ISO8601 timestamp or YYYY-MM-DD date"),
    conn: sqlite3.Connection = Depends(get_db),
) -> List[Dict[str, Any]]:
    since_iso = iso_utc(_parse_since(since))
    return finance_repo.export_since(conn, since_iso)
