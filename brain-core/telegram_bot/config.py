import logging
import os
from datetime import datetime, time as dt_time
from typing import List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("brain-telegram-bot")

BRAIN_URL = os.getenv("BRAIN_URL", "http://brain-api:8000")
BRAIN_TOKEN = os.getenv("BRAIN_SHARED_TOKEN", "")
BRAIN_TELEGRAM_KEY = os.getenv("BRAIN_TELEGRAM_KEY") or BRAIN_TOKEN
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BRAIN_DB_PATH = os.getenv("BRAIN_DB_PATH", "/app/data/brain.db")
RATE_LIMIT_SECONDS = float(os.getenv("BRAIN_BOT_RATE_LIMIT_SECONDS", "1.0"))
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
DIGEST_TIME_STR = os.getenv("DIGEST_TIME", "08:00")
WEEKLY_DIGEST_ENABLED = os.getenv("WEEKLY_DIGEST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
WEEKLY_DIGEST_TIME_STR = os.getenv("WEEKLY_DIGEST_TIME", "20:00")
WEEKLY_DIGEST_WEEKDAY_STR = os.getenv("WEEKLY_DIGEST_WEEKDAY", "sun")
_digest_chat_ids_raw = os.getenv("DIGEST_CHAT_IDS", "")
MOOD_TIME_STR = os.getenv("MOOD_TIME", "21:30")
BRAIN_BOT_DB_PATH = os.getenv("BRAIN_BOT_DB_PATH", "/app/data/bot.db")


def get_digest_tz() -> ZoneInfo:
    import logging

    logger = logging.getLogger("brain-telegram-bot")
    try:
        return ZoneInfo(os.getenv("TZ", "Europe/Rome"))
    except Exception:
        logger.warning("Invalid TZ for digest, falling back to Europe/Rome.")
        return ZoneInfo("Europe/Rome")


def _parse_digest_chat_ids(raw: str) -> List[int]:
    chat_ids: List[int] = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            chat_ids.append(int(candidate))
        except ValueError:
            logger.warning("ignoring invalid chat id in DIGEST_CHAT_IDS: %s", candidate)
    return chat_ids


def _parse_digest_time(raw: str) -> Optional[dt_time]:
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        logger.warning("Invalid DIGEST_TIME format (expected HH:MM): %s", raw)
        return None


def _parse_weekday(raw: str) -> Optional[int]:
    if not raw:
        return None
    candidate = raw.strip().lower()
    if candidate.isdigit():
        value = int(candidate)
        if 0 <= value <= 6:
            return value
    mapping = {
        "mon": 0,
        "monday": 0,
        "lun": 0,
        "lunedì": 0,
        "tue": 1,
        "tuesday": 1,
        "mar": 1,
        "martedi": 1,
        "mer": 2,
        "wed": 2,
        "wednesday": 2,
        "gio": 3,
        "thu": 3,
        "thursday": 3,
        "ven": 4,
        "fri": 4,
        "friday": 4,
        "sab": 5,
        "sat": 5,
        "saturday": 5,
        "dom": 6,
        "sun": 6,
        "sunday": 6,
        "domenica": 6,
    }
    return mapping.get(candidate)


DIGEST_CHAT_IDS: List[int] = _parse_digest_chat_ids(_digest_chat_ids_raw)
DIGEST_TIME: Optional[dt_time] = _parse_digest_time(DIGEST_TIME_STR)
MOOD_TIME: Optional[dt_time] = _parse_digest_time(MOOD_TIME_STR)
WEEKLY_DIGEST_TIME: Optional[dt_time] = _parse_digest_time(WEEKLY_DIGEST_TIME_STR)
_weekly_weekday = _parse_weekday(WEEKLY_DIGEST_WEEKDAY_STR)
WEEKLY_DIGEST_WEEKDAY = _weekly_weekday if _weekly_weekday is not None else 6
