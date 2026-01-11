from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from brain_api.app import utils


def test_amount_to_cents_rounding() -> None:
    assert utils.amount_to_cents(1.23) == 123
    assert utils.amount_to_cents(1.235) == 124
    assert utils.amount_to_cents(1.234) == 123


def test_amount_to_cents_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        utils.amount_to_cents("not-a-number")
    assert exc.value.status_code == 400


def test_normalize_text() -> None:
    assert utils.normalize_text(None) == ""
    assert utils.normalize_text("  a  ") == "a"
    assert utils.normalize_text("   ") == ""


def test_normalize_category() -> None:
    assert utils.normalize_category("  food ") == "food"


def test_parse_ts() -> None:
    parsed = utils._parse_ts("2026-01-10T10:00:00Z")
    assert parsed == datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)

    assert utils._parse_ts("", allow_empty=True) is None

    with pytest.raises(HTTPException) as exc:
        utils._parse_ts("", allow_empty=False)
    assert exc.value.status_code == 400


def test_parse_since() -> None:
    parsed = utils._parse_since("2026-01-10T10:00:00Z")
    assert parsed == datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(HTTPException) as exc:
        utils._parse_since("")
    assert exc.value.status_code == 400


def test_iso_utc() -> None:
    naive = datetime(2026, 1, 10, 10, 0, 0)
    assert utils.iso_utc(naive) == "2026-01-10T10:00:00+00:00"


def test_as_utc() -> None:
    naive = datetime(2026, 1, 10, 10, 0, 0)
    assert utils._as_utc(naive) == "2026-01-10T10:00:00+00:00"

    aware = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert utils._as_utc(aware) == "2026-01-10T10:00:00+00:00"


def test_cents_to_float() -> None:
    assert utils._cents_to_float(123) == 1.23
