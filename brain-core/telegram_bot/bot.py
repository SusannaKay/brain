import asyncio
import logging
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Dict, List, Optional

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import brain_client
import config
import handlers
import mood_flow
import scheduler
from vision import db as vision_db
from bot_helpers import _build_continue_keyboard
from formatters import (
    _filter_month,
    _format_avg,
    _format_expenses_list,
    _format_month_report,
    _format_mood_checkin,
    _format_mood_week_line,
    _month_year_for_arg,
    _parse_month_arg,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("brain-telegram-bot")

BRAIN_URL = config.BRAIN_URL
BRAIN_TOKEN = config.BRAIN_TOKEN
BRAIN_TELEGRAM_KEY = config.BRAIN_TELEGRAM_KEY
TELEGRAM_BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
RATE_LIMIT_SECONDS = config.RATE_LIMIT_SECONDS
DIGEST_ENABLED = config.DIGEST_ENABLED
DIGEST_TIME_STR = config.DIGEST_TIME_STR
WEEKLY_DIGEST_ENABLED = config.WEEKLY_DIGEST_ENABLED
WEEKLY_DIGEST_TIME_STR = config.WEEKLY_DIGEST_TIME_STR
WEEKLY_DIGEST_WEEKDAY_STR = config.WEEKLY_DIGEST_WEEKDAY_STR
MOOD_TIME_STR = config.MOOD_TIME_STR
BRAIN_BOT_DB_PATH = config.BRAIN_BOT_DB_PATH

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
if not BRAIN_TOKEN:
    raise RuntimeError("BRAIN_SHARED_TOKEN is required")
if not BRAIN_TELEGRAM_KEY:
    raise RuntimeError("BRAIN_TELEGRAM_KEY is required")

user_categories: Dict[int, str] = {}
last_command_at: Dict[int, float] = {}

DIGEST_CHAT_IDS: List[int] = config.DIGEST_CHAT_IDS
DIGEST_TIME: Optional[dt_time] = config.DIGEST_TIME
MOOD_TIME: Optional[dt_time] = config.MOOD_TIME
WEEKLY_DIGEST_TIME: Optional[dt_time] = config.WEEKLY_DIGEST_TIME
WEEKLY_DIGEST_WEEKDAY = config.WEEKLY_DIGEST_WEEKDAY
DIGEST_TZ = config.get_digest_tz()


def _is_rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    last_used = last_command_at.get(user_id)
    if last_used is not None and (now - last_used) < RATE_LIMIT_SECONDS:
        return True
    last_command_at[user_id] = now
    return False


async def _guard_rate_limit(update: Update) -> bool:
    user = update.effective_user
    user_id = user.id if user else 0
    if _is_rate_limited(user_id):
        logger.info("rate_limited user_id=%s username=%s", user_id, user.username if user else "unknown")
        if update.message:
            await update.message.reply_text("Un comando alla volta, grazie ⏳")
        return True
    return False


def _log_command(name: str, update: Update, args: Optional[list] = None) -> None:
    user = update.effective_user
    logger.info(
        "command=%s user_id=%s username=%s chat_id=%s args=%s",
        name,
        user.id if user else "unknown",
        user.username if user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
        args if args is not None else [],
    )


async def post_expense(amount: float, note: Optional[str], category: Optional[str]) -> str:
    payload = {
        "amount": amount,
        "note": note or None,
        "category": category or None,
    }
    headers = {"X-TELEGRAM-KEY": BRAIN_TELEGRAM_KEY}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{BRAIN_URL}/finance/expense/telegram", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            category_label = data.get("category")
            category_suffix = f" · {category_label}" if category_label and category_label != "uncategorized" else ""
            return f"Aggiunta spesa di {data['amount']:.2f}€{category_suffix}"
    except httpx.HTTPStatusError as exc:
        logger.error("API returned error: status=%s body=%s", exc.response.status_code, exc.response.text)
        return "Errore dal brain-api. Riprova più tardi."
    except httpx.RequestError as exc:
        logger.error("Failed to reach brain-api: %s", exc)
        return "Brain non raggiungibile ora."


async def fetch_summary() -> Optional[dict]:
    headers = {"X-BRAIN-TOKEN": BRAIN_TOKEN}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BRAIN_URL}/finance/summary", headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("API returned error: status=%s body=%s", exc.response.status_code, exc.response.text)
    except httpx.RequestError as exc:
        logger.error("Failed to reach brain-api: %s", exc)
    return None


async def fetch_export(since: str) -> Optional[List[dict]]:
    headers = {"X-BRAIN-TOKEN": BRAIN_TOKEN}
    params = {"since": since}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{BRAIN_URL}/finance/export", headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
            logger.error("API returned error: status=%s body=%s", exc.response.status_code, exc.response.text)
    except httpx.RequestError as exc:
        logger.error("Failed to reach brain-api: %s", exc)
    return None


async def fetch_mood_last() -> Optional[dict]:
    headers = {"X-BRAIN-TOKEN": BRAIN_TOKEN}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BRAIN_URL}/mood/last", headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("API returned error: status=%s body=%s", exc.response.status_code, exc.response.text)
    except httpx.RequestError as exc:
        logger.error("Failed to reach brain-api: %s", exc)
    return None


async def fetch_mood_week(days: int = 7) -> Optional[dict]:
    headers = {"X-BRAIN-TOKEN": BRAIN_TOKEN}
    params = {"days": days}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BRAIN_URL}/mood/week", headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("API returned error: status=%s body=%s", exc.response.status_code, exc.response.text)
    except httpx.RequestError as exc:
        logger.error("Failed to reach brain-api: %s", exc)
    return None


scheduler.bind(
    digest_time=DIGEST_TIME,
    digest_chat_ids=DIGEST_CHAT_IDS,
    digest_time_str=DIGEST_TIME_STR,
    digest_tz=DIGEST_TZ,
    weekly_digest_enabled=WEEKLY_DIGEST_ENABLED,
    weekly_digest_time=WEEKLY_DIGEST_TIME,
    weekly_digest_time_str=WEEKLY_DIGEST_TIME_STR,
    weekly_digest_weekday=WEEKLY_DIGEST_WEEKDAY,
    mood_time=MOOD_TIME,
    mood_time_str=MOOD_TIME_STR,
    fetch_summary=fetch_summary,
    fetch_mood_week=fetch_mood_week,
)


def _get_brain_client(context: ContextTypes.DEFAULT_TYPE) -> Optional[brain_client.BrainClient]:
    return context.application.bot_data.get("brain_client")


async def _post_init(application: Application) -> None:
    if DIGEST_ENABLED:
        application.create_task(scheduler._digest_loop(application))
    else:
        logger.info("Daily digest disabled. Set DIGEST_ENABLED=true to activate.")

    application.create_task(scheduler._weekly_mood_digest_loop(application))
    application.create_task(scheduler._mood_prompt_loop(application))
    application.create_task(scheduler._mood_expiry_loop())
    client = application.bot_data.get("brain_client")
    if isinstance(client, brain_client.BrainClient):
        application.create_task(brain_client.retry_loop(client))


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    client = brain_client.BrainClient(BRAIN_URL, BRAIN_TOKEN, BRAIN_BOT_DB_PATH)
    application.bot_data["brain_client"] = client
    vision_db.init_vision_db(config.BRAIN_DB_PATH)

    handlers.bind_ctx(
        guard_rate_limit=_guard_rate_limit,
        log_command=_log_command,
        post_expense=post_expense,
        fetch_summary=fetch_summary,
        fetch_export=fetch_export,
        fetch_mood_last=fetch_mood_last,
        fetch_mood_week=fetch_mood_week,
        build_continue_keyboard=_build_continue_keyboard,
        get_brain_client=_get_brain_client,
        format_mood_checkin=_format_mood_checkin,
        format_avg=_format_avg,
        format_mood_week_line=_format_mood_week_line,
        format_expenses_list=_format_expenses_list,
        parse_month_arg=_parse_month_arg,
        month_year_for_arg=_month_year_for_arg,
        filter_month=_filter_month,
        format_month_report=_format_month_report,
        digest_tz=DIGEST_TZ,
        user_categories=user_categories,
        last_command_at=last_command_at,
        mood_flow=mood_flow,
    )

    application.add_handler(CommandHandler(["start", "help"], handlers.start))
    application.add_handler(CommandHandler("spesa", handlers.add_expense))
    application.add_handler(CommandHandler("categoria", handlers.set_category))
    application.add_handler(CommandHandler("chatid", handlers.chat_id))
    application.add_handler(CommandHandler("oggi", handlers.today))
    application.add_handler(CommandHandler("mese", handlers.month))
    application.add_handler(CommandHandler("mood", handlers.mood_command))
    application.add_handler(CommandHandler("mood_last", handlers.mood_last_command))
    application.add_handler(CommandHandler("mood_week", handlers.mood_week_command))
    application.add_handler(CommandHandler("skip", handlers.skip_command))
    application.add_handler(CallbackQueryHandler(handlers.mood_continue_callback, pattern="^mood_continue$"))
    application.add_handler(CallbackQueryHandler(handlers.mood_cancel_callback, pattern="^mood_cancel$"))
    application.add_handler(CallbackQueryHandler(handlers.vision_callback, pattern="^V1\\|"))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handlers.vision_media_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

    application.run_polling()


if __name__ == "__main__":
    main()
