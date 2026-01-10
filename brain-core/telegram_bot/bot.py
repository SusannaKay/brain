import asyncio
import logging
import os
import random
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import brain_client
import mood_flow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("brain-telegram-bot")

BRAIN_URL = os.getenv("BRAIN_URL", "http://brain-api:8000")
BRAIN_TOKEN = os.getenv("BRAIN_SHARED_TOKEN", "")
BRAIN_TELEGRAM_KEY = os.getenv("BRAIN_TELEGRAM_KEY") or BRAIN_TOKEN
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RATE_LIMIT_SECONDS = float(os.getenv("BRAIN_BOT_RATE_LIMIT_SECONDS", "1.0"))
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
DIGEST_TIME_STR = os.getenv("DIGEST_TIME", "08:00")
WEEKLY_DIGEST_ENABLED = os.getenv("WEEKLY_DIGEST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
WEEKLY_DIGEST_TIME_STR = os.getenv("WEEKLY_DIGEST_TIME", "20:00")
WEEKLY_DIGEST_WEEKDAY_STR = os.getenv("WEEKLY_DIGEST_WEEKDAY", "sun")
_digest_chat_ids_raw = os.getenv("DIGEST_CHAT_IDS", "")
MOOD_TIME_STR = os.getenv("MOOD_TIME", "21:30")
BRAIN_BOT_DB_PATH = os.getenv("BRAIN_BOT_DB_PATH", "/app/data/bot.db")
try:
    DIGEST_TZ = ZoneInfo(os.getenv("TZ", "Europe/Rome"))
except Exception:
    logger.warning("Invalid TZ for digest, falling back to Europe/Rome.")
    DIGEST_TZ = ZoneInfo("Europe/Rome")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
if not BRAIN_TOKEN:
    raise RuntimeError("BRAIN_SHARED_TOKEN is required")
if not BRAIN_TELEGRAM_KEY:
    raise RuntimeError("BRAIN_TELEGRAM_KEY is required")

user_categories: Dict[int, str] = {}
last_command_at: Dict[int, float] = {}


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


def _format_ts(ts_value: Optional[str]) -> str:
    if not ts_value:
        return ""
    try:
        sanitized = ts_value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(sanitized)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts_value


def _format_avg(value: Optional[float]) -> str:
    return f"{value:.1f}" if value is not None else "—"


def _format_waste_spend(value: Optional[object]) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sì" if value else "No"
    try:
        return "Sì" if int(value) == 1 else "No"
    except (TypeError, ValueError):
        return "—"


def _format_mood_checkin(item: dict) -> str:
    local_date = item.get("local_date") or "----"
    slot = item.get("slot") or ""
    header = f"{local_date} ({slot})" if slot else local_date
    mood = item.get("mood_score")
    energy = item.get("energy_level")
    waste = _format_waste_spend(item.get("waste_spend"))
    lines = [
        header,
        f"Mood: {mood} | Energia: {energy} | Spese inutili: {waste}",
    ]
    mood_text = item.get("mood_text")
    if mood_text:
        lines.append(f"Nota: {mood_text}")
    did_thing = item.get("did_thing")
    if did_thing:
        lines.append(f"Fatto: {did_thing}")
    return "\n".join(lines)


def _format_mood_week_line(item: dict) -> str:
    local_date = item.get("local_date") or "----"
    slot = item.get("slot") or ""
    mood = item.get("mood_score")
    energy = item.get("energy_level")
    prefix = f"{local_date} ({slot})" if slot else local_date
    return f"{prefix}: mood {mood}, energia {energy}"


def _format_expenses_list(expenses: list) -> str:
    lines = []
    for item in expenses:
        ts = _format_ts(item.get("ts"))
        note = item.get("note")
        category = item.get("category") or "uncategorized"
        line = f"• {item.get('amount', 0):.2f}€ · {category} · {ts}" if ts else f"• {item.get('amount', 0):.2f}€ · {category}"
        if note:
            line += f" · {note}"
        lines.append(line)
    return "\n".join(lines) if lines else "Nessuna spesa recente."


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


def _next_digest_datetime(now: datetime, digest_time: dt_time) -> datetime:
    target = datetime.combine(now.date(), digest_time, tzinfo=DIGEST_TZ)
    if now >= target:
        target += timedelta(days=1)
    return target


def _next_weekly_digest_datetime(now: datetime, digest_time: dt_time, weekday: int) -> datetime:
    days_ahead = (weekday - now.weekday()) % 7
    target = datetime.combine(now.date(), digest_time, tzinfo=DIGEST_TZ) + timedelta(days=days_ahead)
    if now >= target:
        target += timedelta(days=7)
    return target


def _format_top_categories_line(summary: dict) -> str:
    categories = summary.get("top_categories") or []
    if not categories:
        return "🏷️ Top oggi: niente di memorabile."
    pairs = [f"{item.get('category', 'uncategorized')}: {item.get('total', 0):.2f}€" for item in categories[:3]]
    return "🏷️ Top oggi: " + ", ".join(pairs)


def _oracle_line(summary: dict) -> str:
    today_total = summary.get("today_total", 0)
    month_total = summary.get("month_total", 0)
    ideas = [
        f"Il contabile immaginario annota {today_total:.2f}€ per oggi e alza un sopracciglio.",
        f"Il mese è a {month_total:.2f}€: l'oracolo consiglia scarpe con tasche segrete.",
        "Una ricevuta volante dice che domani spenderai solo in sogni lucidi.",
        "Hai sbloccato il livello 'responsabile ma sospettoso' del portafoglio.",
        "Il ledger cosmico ti dà il cinque e se ne va senza spiegazioni.",
        "Un gabbiano passa, urla 'budget' e nessuno sa perché.",
    ]
    return random.choice(ideas)


def _parse_month_arg(args: List[str]) -> Optional[int]:
    if not args:
        return None
    try:
        value = int(args[0])
    except ValueError:
        return None
    if 1 <= value <= 12:
        return value
    return None


def _month_year_for_arg(target_month: int, now: datetime) -> (int, int):
    if target_month > now.month:
        return now.year - 1, target_month
    return now.year, target_month


def _parse_ts_to_dt(ts_value: str) -> Optional[datetime]:
    try:
        sanitized = ts_value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(sanitized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except ValueError:
        return None


def _filter_month(expenses: List[dict], year: int, month: int) -> List[dict]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    filtered: List[dict] = []
    for item in expenses:
        ts_raw = item.get("ts")
        ts_dt = _parse_ts_to_dt(ts_raw) if isinstance(ts_raw, str) else None
        if ts_dt and start <= ts_dt < end:
            filtered.append(item)
    return filtered


def _format_month_report(expenses: List[dict], year: int, month: int) -> str:
    incomes, expenses_total = _compute_totals(expenses)
    latest = sorted(expenses, key=lambda x: x.get("ts") or "", reverse=True)[:5]
    latest_block = _format_expenses_list(latest) if latest else "Nessuna spesa registrata."
    return (
        f"🗓️ Mese ({year}-{month:02d})\n"
        f"Entrate: {incomes:.2f}€\n"
        f"Uscite: {expenses_total:.2f}€\n"
        f"Ultime spese del mese:\n{latest_block}"
    )


def _compute_totals(expenses: List[dict]) -> (float, float):
    incomes = 0.0
    expenses_total = 0.0
    for item in expenses:
        amount = float(item.get("amount", 0) or 0)
        if amount >= 0:
            incomes += amount
        else:
            expenses_total += abs(amount)
    return incomes, expenses_total


def _build_digest_message(summary: dict) -> str:
    today_total = summary.get("today_total", 0)
    month_total = summary.get("month_total", 0)
    today_label = summary.get("today_date", "---")
    month_label = summary.get("month", "---")
    lines = [
        "🌅 Daily Digest",
        f"📅 Oggi ({today_label}): {today_total:.2f}€",
        f"🗓️ Mese ({month_label}): {month_total:.2f}€",
        _format_top_categories_line(summary),
        f"🔮 {_oracle_line(summary)}",
    ]
    return "\n".join(lines)


def _build_weekly_mood_digest(week_data: dict) -> str:
    aggregates = week_data.get("aggregates") or {}
    items = week_data.get("items") or []
    count = int(aggregates.get("count") or 0)
    avg_mood = _format_avg(aggregates.get("avg_mood_score"))
    avg_energy = _format_avg(aggregates.get("avg_energy_level"))
    waste_count = int(aggregates.get("waste_spend_count") or 0)

    best = max(items, key=lambda item: item.get("mood_score", -99), default=None)
    worst = min(items, key=lambda item: item.get("mood_score", 99), default=None)
    best_label = f"{best.get('local_date')} ({best.get('mood_score')})" if best else "—"
    worst_label = f"{worst.get('local_date')} ({worst.get('mood_score')})" if worst else "—"

    lines = [
        f"Settimana mood: avg {avg_mood} | energia: avg {avg_energy} | check-in: {count}",
        f"Spese inutili: {waste_count} giorni",
        f"Giorni migliori/peggiori: {best_label} / {worst_label}",
        "C’è qualcosa che ha inciso sull’energia questa settimana?",
    ]
    return "\n".join(lines)


async def _send_digest(application: Application) -> None:
    summary = await fetch_summary()
    if not summary:
        logger.warning("Skipping daily digest: summary unavailable.")
        return
    message = _build_digest_message(summary)
    for chat_id in DIGEST_CHAT_IDS:
        try:
            await application.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logger.exception("Failed to send digest to chat_id=%s", chat_id)


async def _send_weekly_mood_digest(application: Application) -> None:
    week_data = await fetch_mood_week(7)
    if not week_data:
        logger.warning("Skipping weekly mood digest: data unavailable.")
        return
    aggregates = week_data.get("aggregates") or {}
    count = int(aggregates.get("count") or 0)
    if count < 3:
        message = f"Pochi check-in questa settimana ({count}). Nessun digest completo."
    else:
        message = _build_weekly_mood_digest(week_data)
    for chat_id in DIGEST_CHAT_IDS:
        try:
            await application.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logger.exception("Failed to send weekly mood digest to chat_id=%s", chat_id)


async def _digest_loop(application: Application) -> None:
    if not DIGEST_TIME:
        logger.info("Daily digest disabled: invalid DIGEST_TIME.")
        return
    if not DIGEST_CHAT_IDS:
        logger.info("Daily digest disabled: DIGEST_CHAT_IDS is empty.")
        return
    logger.info(
        "Daily digest enabled at %s Europe/Rome for chats=%s",
        DIGEST_TIME_STR,
        ",".join(str(x) for x in DIGEST_CHAT_IDS),
    )
    while True:
        now = datetime.now(DIGEST_TZ)
        next_run = _next_digest_datetime(now, DIGEST_TIME)
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
    if not WEEKLY_DIGEST_ENABLED:
        logger.info("Weekly mood digest disabled: WEEKLY_DIGEST_ENABLED=false.")
        return
    if not WEEKLY_DIGEST_TIME:
        logger.info("Weekly mood digest disabled: invalid WEEKLY_DIGEST_TIME.")
        return
    if not DIGEST_CHAT_IDS:
        logger.info("Weekly mood digest disabled: DIGEST_CHAT_IDS is empty.")
        return
    logger.info(
        "Weekly mood digest enabled at %s weekday=%s Europe/Rome for chats=%s",
        WEEKLY_DIGEST_TIME_STR,
        WEEKLY_DIGEST_WEEKDAY,
        ",".join(str(x) for x in DIGEST_CHAT_IDS),
    )
    while True:
        now = datetime.now(DIGEST_TZ)
        next_run = _next_weekly_digest_datetime(now, WEEKLY_DIGEST_TIME, WEEKLY_DIGEST_WEEKDAY)
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


def _build_continue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Continua", callback_data="mood_continue"),
                InlineKeyboardButton("Annulla", callback_data="mood_cancel"),
            ]
        ]
    )


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
    if not MOOD_TIME:
        logger.info("Mood prompts disabled: invalid MOOD_TIME.")
        return
    if not DIGEST_CHAT_IDS:
        logger.info("Mood prompts disabled: DIGEST_CHAT_IDS is empty.")
        return
    logger.info(
        "Mood prompts enabled at %s Europe/Rome for chats=%s",
        MOOD_TIME_STR,
        ",".join(str(x) for x in DIGEST_CHAT_IDS),
    )
    while True:
        now = datetime.now(DIGEST_TZ)
        next_run = _next_digest_datetime(now, MOOD_TIME)
        sleep_seconds = max(0, (next_run - now).total_seconds())
        logger.info("Next mood prompt at %s (sleeping %.0fs)", next_run.isoformat(), sleep_seconds)
        try:
            await asyncio.sleep(sleep_seconds)
            for chat_id in DIGEST_CHAT_IDS:
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


def _get_brain_client(context: ContextTypes.DEFAULT_TYPE) -> Optional[brain_client.BrainClient]:
    return context.application.bot_data.get("brain_client")


async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("mood", update, context.args)
    chat = update.effective_chat
    if not chat or not update.message:
        return
    chat_id = chat.id
    now = mood_flow.utcnow()
    if mood_flow.expire_if_needed(chat_id, now):
        pass
    state = mood_flow.get_state(chat_id)
    if state and mood_flow.is_open(state):
        await update.message.reply_text(
            "Check-in già in corso. Vuoi continuare o annullare?",
            reply_markup=_build_continue_keyboard(),
        )
        return
    response = mood_flow.start_checkin(chat_id, slot="manual", now=now)
    if response:
        await update.message.reply_text(response.text, reply_markup=response.reply_markup)


async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("skip", update, context.args)
    chat = update.effective_chat
    if not chat or not update.message:
        return
    chat_id = chat.id
    if mood_flow.cancel_checkin(chat_id):
        await update.message.reply_text("Check-in annullato.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Nessun check-in attivo.")


async def mood_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat = update.effective_chat
    if not chat:
        return
    chat_id = chat.id
    now = mood_flow.utcnow()
    if mood_flow.expire_if_needed(chat_id, now):
        return
    response = mood_flow.handle_text(chat_id, update.message.text, now)
    if not response:
        return
    await update.message.reply_text(response.text, reply_markup=response.reply_markup)
    if response.completed_payload:
        client = _get_brain_client(context)
        if client:
            await client.post_mood_checkin(response.completed_payload)


async def mood_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("mood_last", update, context.args)
    if not update.message:
        return
    data = await fetch_mood_last()
    if not data:
        await update.message.reply_text("Brain non disponibile.")
        return
    payload = data.get("data") if isinstance(data, dict) else None
    if not payload:
        await update.message.reply_text("Nessun check-in trovato.")
        return
    message = "🧭 Ultimo check-in\n" + _format_mood_checkin(payload)
    await update.message.reply_text(message)


async def mood_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("mood_week", update, context.args)
    if not update.message:
        return
    data = await fetch_mood_week(7)
    if not data:
        await update.message.reply_text("Brain non disponibile.")
        return
    aggregates = data.get("aggregates") or {}
    items = data.get("items") or []
    count = int(aggregates.get("count") or 0)
    avg_mood = _format_avg(aggregates.get("avg_mood_score"))
    avg_energy = _format_avg(aggregates.get("avg_energy_level"))
    waste_count = int(aggregates.get("waste_spend_count") or 0)
    lines = [
        "📊 Ultimi 7 giorni",
        f"Check-in: {count} | Mood medio: {avg_mood} | Energia media: {avg_energy} | Spese inutili: {waste_count}",
    ]
    if items:
        lines.extend([f"• {_format_mood_week_line(item)}" for item in items])
    await update.message.reply_text("\n".join(lines))


async def mood_continue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    chat_id = query.message.chat_id
    now = mood_flow.utcnow()
    if mood_flow.expire_if_needed(chat_id, now):
        await query.edit_message_reply_markup(reply_markup=None)
        return
    response = mood_flow.continue_prompt(chat_id)
    if response:
        await query.message.reply_text(response.text, reply_markup=response.reply_markup)
    await query.edit_message_reply_markup(reply_markup=None)


async def mood_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    chat_id = query.message.chat_id
    if mood_flow.cancel_checkin(chat_id):
        await query.message.reply_text("Check-in annullato.", reply_markup=ReplyKeyboardRemove())
    await query.edit_message_reply_markup(reply_markup=None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("start", update, context.args)
    await update.message.reply_text(
        "Ciao! Sono il tuo Brain bot.\n"
        "• /spesa <importo> <nota> aggiunge una spesa\n"
        "• /categoria <nome> imposta la categoria di default\n"
        "• /oggi riepilogo spese di oggi\n"
        "• /mese [numero_mese] riepilogo del mese\n"
        "• /mood avvia un check-in\n"
        "• /mood_last ultimo check-in\n"
        "• /mood_week riepilogo ultimi 7 giorni"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("help", update, context.args)
    await update.message.reply_text(
        "Comandi disponibili:\n"
        "• /spesa <importo> <nota> aggiunge una spesa\n"
        "• /categoria <nome> imposta la categoria di default\n"
        "• /oggi riepilogo spese di oggi\n"
        "• /mese [numero_mese] riepilogo del mese\n"
        "• /mood avvia un check-in\n"
        "• /mood_last ultimo check-in\n"
        "• /mood_week riepilogo ultimi 7 giorni"
    )


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("chatid", update, context.args)
    chat = update.effective_chat
    if not chat:
        await update.message.reply_text("Non riesco a capire questa chat.")
        return
    await update.message.reply_text(f"chat_id: {chat.id} (tipo: {chat.type})")


async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("categoria", update, context.args)
    if not context.args:
        await update.message.reply_text("Usa /categoria <nome> per impostare la categoria di default.")
        return
    category = " ".join(context.args).strip()
    if not category:
        await update.message.reply_text("Categoria non valida.")
        return
    user_id = update.effective_user.id
    user_categories[user_id] = category
    await update.message.reply_text(f"Categoria impostata su '{category}'.")


async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("spesa", update, context.args)
    if not context.args:
        await update.message.reply_text("Uso: /spesa <importo> <nota opzionale>")
        return
    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Importo non valido. Esempio: /spesa 12.50 pranzo.")
        return
    note = " ".join(context.args[1:]).strip() if len(context.args) > 1 else ""
    category = user_categories.get(update.effective_user.id)
    message = await post_expense(amount, note or None, category)
    await update.message.reply_text(message)


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("oggi", update, context.args)
    data = await fetch_summary()
    if not data:
        await update.message.reply_text("Brain non disponibile.")
        return
    expenses_block = _format_expenses_list(data.get("latest", [])[:5])
    await update.message.reply_text(
        f"📅 Oggi ({data['today_date']}): {data['today_total']:.2f}€\n"
        f"Ultime spese:\n{expenses_block}"
    )


async def month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("mese", update, context.args)

    # Decide which month to show: current if no args, else specific month number.
    now = datetime.now(DIGEST_TZ)
    target_month = _parse_month_arg(context.args or [])
    if target_month is None:
        year, month_number = now.year, now.month
    else:
        year, month_number = _month_year_for_arg(target_month, now)

    # Fetch export from start of month and filter client-side.
    since = f"{year}-{month_number:02d}-01"
    expenses = await fetch_export(since)
    if expenses is None:
        await update.message.reply_text("Brain non disponibile.")
        return
    filtered = _filter_month(expenses, year, month_number)
    await update.message.reply_text(_format_month_report(filtered, year, month_number))


async def _post_init(application: Application) -> None:
    if DIGEST_ENABLED:
        application.create_task(_digest_loop(application))
    else:
        logger.info("Daily digest disabled. Set DIGEST_ENABLED=true to activate.")

    application.create_task(_weekly_mood_digest_loop(application))
    application.create_task(_mood_prompt_loop(application))
    application.create_task(_mood_expiry_loop())
    client = application.bot_data.get("brain_client")
    if isinstance(client, brain_client.BrainClient):
        application.create_task(brain_client.retry_loop(client))


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    client = brain_client.BrainClient(BRAIN_URL, BRAIN_TOKEN, BRAIN_BOT_DB_PATH)
    application.bot_data["brain_client"] = client

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("spesa", add_expense))
    application.add_handler(CommandHandler("categoria", set_category))
    application.add_handler(CommandHandler("chatid", chat_id))
    application.add_handler(CommandHandler("oggi", today))
    application.add_handler(CommandHandler("mese", month))
    application.add_handler(CommandHandler("mood", mood_command))
    application.add_handler(CommandHandler("mood_last", mood_last_command))
    application.add_handler(CommandHandler("mood_week", mood_week_command))
    application.add_handler(CommandHandler("skip", skip_command))
    application.add_handler(CallbackQueryHandler(mood_continue_callback, pattern="^mood_continue$"))
    application.add_handler(CallbackQueryHandler(mood_cancel_callback, pattern="^mood_cancel$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mood_message))

    application.run_polling()


if __name__ == "__main__":
    main()
