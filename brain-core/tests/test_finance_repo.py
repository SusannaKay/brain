from __future__ import annotations

from datetime import datetime, timezone

from brain_api.app import finance_repo
from brain_api.app.models import BulkExpense, ExpenseIn


def test_save_expense_inserts(db_conn) -> None:
    expense = ExpenseIn(amount=1.23, note="  coffee  ", category="", ts="2026-01-10T10:00:00Z")
    result = finance_repo.save_expense(db_conn, expense, source="telegram")

    assert set(result.keys()) == {"ts", "amount", "note", "category", "source"}
    assert result["amount"] == 1.23
    assert result["note"] == "coffee"
    assert result["category"] == "uncategorized"
    assert result["source"] == "telegram"


def test_export_since_orders_and_amount(db_conn) -> None:
    first = ExpenseIn(amount=2.0, note="a", category="food", ts="2026-01-10T10:00:00Z")
    second = ExpenseIn(amount=3.5, note="b", category="food", ts="2026-01-10T11:00:00Z")
    finance_repo.save_expense(db_conn, first, source="telegram")
    finance_repo.save_expense(db_conn, second, source="telegram")

    rows = finance_repo.export_since(db_conn, "2026-01-10T00:00:00+00:00")
    assert [row["amount"] for row in rows] == [2.0, 3.5]
    assert [row["ts"] for row in rows] == [
        "2026-01-10T10:00:00+00:00",
        "2026-01-10T11:00:00+00:00",
    ]


def test_bulk_insert_counts_duplicates(db_conn) -> None:
    item = BulkExpense(amount=1.0, ts="2026-01-10T10:00:00Z", note="x", category="misc", source=None)
    inserted = finance_repo.bulk_insert(db_conn, [item, item])
    db_conn.commit()
    assert inserted == 1


def test_sum_between(db_conn) -> None:
    finance_repo.save_expense(
        db_conn,
        ExpenseIn(amount=1.0, note="a", category="food", ts="2026-01-10T10:00:00Z"),
        source="telegram",
    )
    finance_repo.save_expense(
        db_conn,
        ExpenseIn(amount=2.5, note="b", category="food", ts="2026-01-10T11:00:00Z"),
        source="telegram",
    )

    start = datetime(2026, 1, 10, 9, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert finance_repo.sum_between(db_conn, start, end) == 350
