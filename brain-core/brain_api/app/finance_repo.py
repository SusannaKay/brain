import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from .models import BulkExpense, ExpenseIn
from .utils import _as_utc, _cents_to_float, _parse_ts, amount_to_cents, iso_utc, normalize_category, normalize_text


def save_expense(conn: sqlite3.Connection, expense: ExpenseIn, source: str) -> Dict[str, Any]:
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


def sum_between(conn: sqlite3.Connection, start: datetime, end: datetime) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount_cents), 0) FROM finance_expenses
        WHERE ts BETWEEN ? AND ?
        """,
        (_as_utc(start), _as_utc(end)),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def bulk_insert(conn: sqlite3.Connection, expenses: List[BulkExpense]) -> int:
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
    return inserted


def export_since(conn: sqlite3.Connection, since_iso: str) -> List[Dict[str, Any]]:
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
