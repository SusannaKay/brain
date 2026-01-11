import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from typing import Awaitable, Callable, List, Optional

from telegram.ext import Application

from formatters import _build_digest_message, _build_weekly_mood_digest
import mood_flow

logger = logging.getLogger("brain-telegram-bot")


@dataclass
class _SchedulerDeps:
    digest_time: Optional[dt_time]
    digest_chat_ids: List[int]
    digest_time_str: str
    digest_tz: object
    weekly_digest_enabled: bool
    weekly_digest_time: Optional[dt_time]
    weekly_digest_time_str: str
    weekly_digest_weekday: int
    mood_time: Optional[dt_time]
    mood_time_str: str
    fetch_summary: Callable[[], Awaitable[object]]
    fetch_mood_week: Callable[[int], Awaitable[object]]


_DEPS: Optional[_SchedulerDeps] = None


def bind(
    *,
    digest_time: Optional[dt_time],
    digest_chat_ids: List[int],
    digest_time_str: str,
    digest_tz: object,
    weekly_digest_enabled: bool,
    weekly_digest_time: Optional[dt_time],
    weekly_digest_time_str: str,
    weekly_digest_weekday: int,
    mood_time: Optional[dt_time],
    mood_time_str: str,
    fetch_summary: Callable[[], Awaitable[object]],
    fetch_mood_week: Callable[[int], Awaitable[object]],
) -> None:
    global _DEPS
    _DEPS = _SchedulerDeps(
        digest_time=digest_time,
        digest_chat_ids=digest_chat_ids,
        digest_time_str=digest_time_str,
        digest_tz=digest_tz,
        weekly_digest_enabled=weekly_digest_enabled,
        weekly_digest_time=weekly_digest_time,
        weekly_digest_time_str=weekly_digest_time_str,
        weekly_digest_weekday=weekly_digest_weekday,
        mood_time=mood_time,
        mood_time_str=mood_time_str,
        fetch_summary=fetch_summary,
        fetch_mood_week=fetch_mood_week,
    )


def _require_deps() -> _SchedulerDeps:
    if _DEPS is None:
        raise RuntimeError("scheduler.bind must be called before using scheduler loops")
    return _DEPS


def _next_digest_datetime(now: datetime, digest_time: dt_time) -> datetime:
    deps = _require_deps()
    target = datetime.combine(now.date(), digest_time, tzinfo=deps.digest_tz)
    if now >= target:
        target += timedelta(days=1)
    return target


def _next_weekly_digest_datetime(now: datetime, digest_time: dt_time, weekday: int) -> datetime:
    deps = _require_deps()
    days_ahead = (weekday - now.weekday()) % 7
    target = datetime.combine(now.date(), digest_time, tzinfo=deps.digest_tz) + timedelta(days=days_ahead)
    if now >= target:
        target += timedelta(days=7)
    return target


async def _send_digest(application: Application) -> None:
    deps = _require_deps()
    summary = await deps.fetch_summary()
    if not summary:
        logger.warning("Skipping daily digest: summary unavailable.")
        return
    message = _build_digest_message(summary)
    for chat_id in deps.digest_chat_ids:
        try:
            await application.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logger.exception("Failed to send digest to chat_id=%s", chat_id)


async def _send_weekly_mood_digest(application: Application) -> None:
    deps = _require_deps()
    week_data = await deps.fetch_mood_week(7)
    if not week_data:
        logger.warning("Skipping weekly mood digest: data unavailable.")
        return
    aggregates = week_data.get("aggregates") or {}
    count = int(aggregates.get("count") or 0)
    if count < 3:
        message = f"Pochi check-in questa settimana ({count}). Nessun digest completo."
    else:
        message = _build_weekly_mood_digest(week_data)
    for chat_id in deps.digest_chat_ids:
        try:
            await application.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logger.exception("Failed to send weekly mood digest to chat_id=%s", chat_id)


async def _digest_loop(application: Application) -> None:
    deps = _require_deps()
    if not deps.digest_time:
        logger.info("Daily digest disabled: invalid DIGEST_TIME.")
        return
    if not deps.digest_chat_ids:
        logger.info("Daily digest disabled: DIGEST_CHAT_IDS is empty.")
        return
    logger.info(
        "Daily digest enabled at %s Europe/Rome for chats=%s",
        deps.digest_time_str,
        ",".join(str(x) for x in deps.digest_chat_ids),
    )
    while True:
        now = datetime.now(deps.digest_tz)
        next_run = _next_digest_datetime(now, deps.digest_time)
        sleep_seconds = max(0, (next_run - now).total_seconds())
        logger.info("Next daily digest at %s (sleeping %.0fs)", next_run.isoformat(), sleep_seconds)
        try:
            await asyncio.sleep(sleep_seconds)
            await _send_digest(application)
        except asyncio.CancelledError:
            logger.info("Daily digest loop cancelled.")
            raise
        except Exception:
            logger.exception("Unexpected error in daily digest loop.")
            await asyncio.sleep(5)


async def _weekly_mood_digest_loop(application: Application) -> None:
    deps = _require_deps()
    if not deps.weekly_digest_enabled:
        logger.info("Weekly mood digest disabled: WEEKLY_DIGEST_ENABLED=false.")
        return
    if not deps.weekly_digest_time:
        logger.info("Weekly mood digest disabled: invalid WEEKLY_DIGEST_TIME.")
        return
    if not deps.digest_chat_ids:
        logger.info("Weekly mood digest disabled: DIGEST_CHAT_IDS is empty.")
        return
    logger.info(
        "Weekly mood digest enabled at %s weekday=%s Europe/Rome for chats=%s",
        deps.weekly_digest_time_str,
        deps.weekly_digest_weekday,
        ",".join(str(x) for x in deps.digest_chat_ids),
    )
    while True:
        now = datetime.now(deps.digest_tz)
        next_run = _next_weekly_digest_datetime(now, deps.weekly_digest_time, deps.weekly_digest_weekday)
        sleep_seconds = max(0, (next_run - now).total_seconds())
        logger.info("Next weekly mood digest at %s (sleeping %.0fs)", next_run.isoformat(), sleep_seconds)
        try:
            await asyncio.sleep(sleep_seconds)
            await _send_weekly_mood_digest(application)
        except asyncio.CancelledError:
            logger.info("Weekly mood digest loop cancelled.")
            raise
        except Exception:
            logger.exception("Unexpected error in weekly mood digest loop.")
            await asyncio.sleep(5)


async def _send_mood_prompt(application: Application, chat_id: int, slot: str) -> None:
    now = mood_flow.utcnow()
    response = mood_flow.start_checkin(chat_id, slot=slot, now=now)
    if not response:
        return
    try:
        await application.bot.send_message(chat_id=chat_id, text=response.text, reply_markup=response.reply_markup)
    except Exception:
        logger.exception("Failed to send mood prompt to chat_id=%s", chat_id)


async def _mood_prompt_loop(application: Application) -> None:
    deps = _require_deps()
    if not deps.mood_time:
        logger.info("Mood prompts disabled: invalid MOOD_TIME.")
        return
    if not deps.digest_chat_ids:
        logger.info("Mood prompts disabled: DIGEST_CHAT_IDS is empty.")
        return
    logger.info(
        "Mood prompts enabled at %s Europe/Rome for chats=%s",
        deps.mood_time_str,
        ",".join(str(x) for x in deps.digest_chat_ids),
    )
    while True:
        now = datetime.now(deps.digest_tz)
        next_run = _next_digest_datetime(now, deps.mood_time)
        sleep_seconds = max(0, (next_run - now).total_seconds())
        logger.info("Next mood prompt at %s (sleeping %.0fs)", next_run.isoformat(), sleep_seconds)
        try:
            await asyncio.sleep(sleep_seconds)
            for chat_id in deps.digest_chat_ids:
                if mood_flow.is_idle(chat_id):
                    await _send_mood_prompt(application, chat_id, slot="evening")
        except asyncio.CancelledError:
            logger.info("Mood prompt loop cancelled.")
            raise
        except Exception:
            logger.exception("Unexpected error in mood prompt loop.")
            await asyncio.sleep(5)


async def _mood_expiry_loop() -> None:
    while True:
        try:
            expired = mood_flow.expire_stale(mood_flow.utcnow())
            if expired:
                logger.info("Expired mood check-ins: %s", expired)
        except Exception:
            logger.exception("Unexpected error in mood expiry loop.")
        await asyncio.sleep(15 * 60)
