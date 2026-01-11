from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Union

from fastapi import HTTPException, status


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


def _cents_to_float(value: int) -> float:
    return float(Decimal(value) / 100)


def _as_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
