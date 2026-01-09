from datetime import date, datetime
from typing import List, Optional, Union

from pydantic import BaseModel, Field


class ExpenseIn(BaseModel):
    amount: float = Field(..., ne=0)
    note: Optional[str] = None
    category: Optional[str] = None
    ts: Optional[Union[str, date, datetime]] = None


class ExpenseRecord(BaseModel):
    ts: str
    amount: float
    note: Optional[str]
    category: str
    source: str


class ExpenseSummary(BaseModel):
    today_date: str
    today_total: float
    month: str
    month_total: float
    top_categories: List[dict]
    latest: List[ExpenseRecord]


class BulkExpense(BaseModel):
    ts: Union[str, date, datetime]
    amount: float = Field(..., ne=0)
    note: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None


class EventIn(BaseModel):
    module: str
    type: str
    payload_json: dict
    ts: Optional[datetime] = None


class MoodCheckinIn(BaseModel):
    ts: str
    local_date: str
    slot: str
    energy_level: int = Field(..., ge=-2, le=2)
    mood_score: int = Field(..., ge=-3, le=3)
    mood_text: Optional[str] = None
    did_thing: Optional[str] = None
    waste_spend: bool
