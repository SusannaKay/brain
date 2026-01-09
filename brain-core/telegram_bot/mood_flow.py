from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove

logger = logging.getLogger("brain-telegram-bot.mood-flow")

STATUS_IDLE = "IDLE"
STATUS_OPEN = "OPEN"
STATUS_COMPLETED = "COMPLETED"
STATUS_EXPIRED = "EXPIRED"

STEP_ENERGY = "ENERGY"
STEP_MOOD = "MOOD"
STEP_TEXT = "TEXT"
STEP_DID = "DID"
STEP_WASTE = "WASTE"

ENERGY_VALUES = {-2, -1, 0, 1, 2}
MOOD_VALUES = {-3, -2, -1, 0, 1, 2, 3}

TTL_HOURS = 6

try:
    LOCAL_TZ = ZoneInfo(os.getenv("TZ", "Europe/Rome"))
except Exception:
    LOCAL_TZ = ZoneInfo("Europe/Rome")
    logger.warning("Invalid TZ for mood flow, falling back to Europe/Rome.")


@dataclass
class MoodState:
    chat_id: int
    status: str
    step: Optional[str]
    opened_at: datetime
    slot: str
    local_date: str
    energy_level: Optional[int] = None
    mood_score: Optional[int] = None
    mood_text: Optional[str] = None
    did_thing: Optional[str] = None
    waste_spend: Optional[bool] = None


@dataclass
class FlowResponse:
    text: str
    reply_markup: Optional[object] = None
    completed_payload: Optional[dict] = None


_states: Dict[int, MoodState] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_state(chat_id: int) -> Optional[MoodState]:
    return _states.get(chat_id)


def is_open(state: MoodState) -> bool:
    return state.status == STATUS_OPEN


def is_idle(chat_id: int) -> bool:
    state = _states.get(chat_id)
    return state is None or state.status in {STATUS_IDLE, STATUS_COMPLETED, STATUS_EXPIRED}


def is_expired(state: MoodState, now: datetime) -> bool:
    return state.status == STATUS_OPEN and now >= state.opened_at + timedelta(hours=TTL_HOURS)


def expire_stale(now: datetime) -> int:
    expired = 0
    for state in list(_states.values()):
        if is_expired(state, now):
            state.status = STATUS_EXPIRED
            state.step = None
            expired += 1
    return expired


def expire_if_needed(chat_id: int, now: datetime) -> bool:
    state = _states.get(chat_id)
    if not state:
        return False
    if is_expired(state, now):
        state.status = STATUS_EXPIRED
        state.step = None
        return True
    return False


def cancel_checkin(chat_id: int) -> bool:
    state = _states.get(chat_id)
    if not state or state.status != STATUS_OPEN:
        return False
    state.status = STATUS_IDLE
    state.step = None
    return True


def start_checkin(chat_id: int, slot: str, now: datetime) -> Optional[FlowResponse]:
    if not is_idle(chat_id):
        return None
    local_date = now.astimezone(LOCAL_TZ).date().isoformat()
    _states[chat_id] = MoodState(
        chat_id=chat_id,
        status=STATUS_OPEN,
        step=STEP_ENERGY,
        opened_at=now,
        slot=slot,
        local_date=local_date,
    )
    return FlowResponse(
        text="Energia? (-2 a +2)",
        reply_markup=_energy_keyboard(),
    )


def continue_prompt(chat_id: int) -> Optional[FlowResponse]:
    state = _states.get(chat_id)
    if not state or state.status != STATUS_OPEN:
        return None
    if state.step == STEP_ENERGY:
        return FlowResponse(text="Energia? (-2 a +2)", reply_markup=_energy_keyboard())
    if state.step == STEP_MOOD:
        return FlowResponse(text="Mood? (-3 a +3)", reply_markup=_mood_keyboard())
    if state.step == STEP_TEXT:
        return FlowResponse(text="Nota sul mood? (opzionale)", reply_markup=_skip_keyboard())
    if state.step == STEP_DID:
        return FlowResponse(text="Hai fatto qualcosa di rilevante? (opzionale)", reply_markup=_skip_keyboard())
    if state.step == STEP_WASTE:
        return FlowResponse(text="C'è stata dispersione di tempo/energia? (Sì/No)", reply_markup=_waste_keyboard())
    return None


def handle_text(chat_id: int, text: str, now: datetime) -> Optional[FlowResponse]:
    state = _states.get(chat_id)
    if not state or state.status != STATUS_OPEN:
        return None
    if is_expired(state, now):
        state.status = STATUS_EXPIRED
        state.step = None
        return None

    if state.step == STEP_ENERGY:
        value = _parse_int(text)
        if value not in ENERGY_VALUES:
            return FlowResponse(text="Scegli un valore dalla tastiera", reply_markup=_energy_keyboard())
        state.energy_level = value
        state.step = STEP_MOOD
        return FlowResponse(text="Mood? (-3 a +3)", reply_markup=_mood_keyboard())

    if state.step == STEP_MOOD:
        value = _parse_int(text)
        if value not in MOOD_VALUES:
            return FlowResponse(text="Scegli un valore dalla tastiera", reply_markup=_mood_keyboard())
        state.mood_score = value
        state.step = STEP_TEXT
        return FlowResponse(text="Nota sul mood? (opzionale)", reply_markup=_skip_keyboard())

    if state.step == STEP_TEXT:
        state.mood_text = _normalize_optional_text(text)
        state.step = STEP_DID
        return FlowResponse(text="Hai fatto qualcosa di rilevante? (opzionale)", reply_markup=_skip_keyboard())

    if state.step == STEP_DID:
        state.did_thing = _normalize_optional_text(text)
        state.step = STEP_WASTE
        return FlowResponse(text="C'è stata dispersione di tempo/energia? (Sì/No)", reply_markup=_waste_keyboard())

    if state.step == STEP_WASTE:
        waste_value = _parse_yes_no(text)
        if waste_value is None:
            return FlowResponse(text="Scegli un valore dalla tastiera", reply_markup=_waste_keyboard())
        state.waste_spend = waste_value
        state.status = STATUS_COMPLETED
        state.step = None
        payload = {
            "ts": now.isoformat(),
            "local_date": state.local_date,
            "slot": state.slot,
            "energy_level": state.energy_level,
            "mood_score": state.mood_score,
            "mood_text": state.mood_text,
            "did_thing": state.did_thing,
            "waste_spend": state.waste_spend,
        }
        return FlowResponse(text="Ok. Registrato.", reply_markup=ReplyKeyboardRemove(), completed_payload=payload)

    return None


def _normalize_optional_text(text: str) -> Optional[str]:
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.lower() == "salta":
        return None
    return candidate


def _parse_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except ValueError:
        return None


def _parse_yes_no(text: str) -> Optional[bool]:
    normalized = text.strip().lower()
    if normalized in {"si", "sì"}:
        return True
    if normalized in {"no"}:
        return False
    return None


def _energy_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["-2", "-1", "0", "+1", "+2"]], resize_keyboard=True)


def _mood_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["-3", "-2", "-1", "0", "+1", "+2", "+3"]], resize_keyboard=True)


def _skip_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Salta"]], resize_keyboard=True)


def _waste_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Sì", "No"]], resize_keyboard=True)
