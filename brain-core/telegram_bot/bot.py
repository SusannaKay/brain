import asyncio
import logging
import os
import random
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("brain-telegram-bot")

BRAIN_URL = os.getenv("BRAIN_URL", "http://brain-api:8000")
BRAIN_TOKEN = os.getenv("BRAIN_SHARED_TOKEN", "")
BRAIN_TELEGRAM_KEY = os.getenv("BRAIN_TELEGRAM_KEY") or BRAIN_TOKEN
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
RATE_LIMIT_SECONDS = float(os.getenv("BRAIN_BOT_RATE_LIMIT_SECONDS", "1.0"))
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
DIGEST_TIME_STR = os.getenv("DIGEST_TIME", "08:00")
_digest_chat_ids_raw = os.getenv("DIGEST_CHAT_IDS", "")
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


DIGEST_CHAT_IDS: List[int] = _parse_digest_chat_ids(_digest_chat_ids_raw)
DIGEST_TIME: Optional[dt_time] = _parse_digest_time(DIGEST_TIME_STR)


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


def _next_digest_datetime(now: datetime, digest_time: dt_time) -> datetime:
    target = datetime.combine(now.date(), digest_time, tzinfo=DIGEST_TZ)
    if now >= target:
        target += timedelta(days=1)
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("start", update, context.args)
    await update.message.reply_text(
        "Ciao! Sono il tuo Brain bot. Usa /spesa <importo> <nota>, /categoria <nome>, /oggi, /mese [numero_mese]."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_rate_limit(update):
        return
    _log_command("help", update, context.args)
    await update.message.reply_text(
        "Ciao! Sono il tuo Brain bot. Usa /spesa <importo> <nota>, /categoria <nome>, /oggi, /mese [numero_mese]."
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


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("spesa", add_expense))
    application.add_handler(CommandHandler("categoria", set_category))
    application.add_handler(CommandHandler("chatid", chat_id))
    application.add_handler(CommandHandler("oggi", today))
    application.add_handler(CommandHandler("mese", month))

    if DIGEST_ENABLED:
        application.create_task(_digest_loop(application))
    else:
        logger.info("Daily digest disabled. Set DIGEST_ENABLED=true to activate.")

    application.run_polling()


if __name__ == "__main__":
    main()
