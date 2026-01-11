from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Dict, List, Optional

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes


@dataclass
class _HandlerCtx:
    guard_rate_limit: Callable[[Update], Awaitable[bool]]
    log_command: Callable[[str, Update, Optional[list]], None]
    post_expense: Callable[[float, Optional[str], Optional[str]], Awaitable[str]]
    fetch_summary: Callable[[], Awaitable[Optional[dict]]]
    fetch_export: Callable[[str], Awaitable[Optional[List[dict]]]]
    fetch_mood_last: Callable[[], Awaitable[Optional[dict]]]
    fetch_mood_week: Callable[[int], Awaitable[Optional[dict]]]
    build_continue_keyboard: Callable[[], object]
    get_brain_client: Callable[[ContextTypes.DEFAULT_TYPE], object]
    format_mood_checkin: Callable[[dict], str]
    format_avg: Callable[[Optional[float]], str]
    format_mood_week_line: Callable[[dict], str]
    format_expenses_list: Callable[[list], str]
    parse_month_arg: Callable[[List[str]], Optional[int]]
    month_year_for_arg: Callable[[int, datetime], tuple]
    filter_month: Callable[[List[dict], int, int], List[dict]]
    format_month_report: Callable[[List[dict], int, int], str]
    digest_tz: object
    user_categories: Dict[int, str]
    last_command_at: Dict[int, float]
    mood_flow: object


_CTX: Optional[_HandlerCtx] = None


def bind_ctx(ctx: _HandlerCtx | None = None, **kwargs) -> None:
    global _CTX
    if ctx is not None:
        _CTX = ctx
    else:
        _CTX = _HandlerCtx(**kwargs)


def _require_ctx() -> _HandlerCtx:
    if _CTX is None:
        raise RuntimeError("handlers.bind_ctx must be called before using handlers")
    return _CTX


async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("mood", update, context.args)
    chat = update.effective_chat
    if not chat or not update.message:
        return
    chat_id = chat.id
    now = ctx.mood_flow.utcnow()
    if ctx.mood_flow.expire_if_needed(chat_id, now):
        pass
    state = ctx.mood_flow.get_state(chat_id)
    if state and ctx.mood_flow.is_open(state):
        await update.message.reply_text(
            "Check-in già in corso. Vuoi continuare o annullare?",
            reply_markup=ctx.build_continue_keyboard(),
        )
        return
    response = ctx.mood_flow.start_checkin(chat_id, slot="manual", now=now)
    if response:
        await update.message.reply_text(response.text, reply_markup=response.reply_markup)


async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("skip", update, context.args)
    chat = update.effective_chat
    if not chat or not update.message:
        return
    chat_id = chat.id
    if ctx.mood_flow.cancel_checkin(chat_id):
        await update.message.reply_text("Check-in annullato.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Nessun check-in attivo.")


async def mood_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if not update.message:
        return
    chat = update.effective_chat
    if not chat:
        return
    chat_id = chat.id
    now = ctx.mood_flow.utcnow()
    if ctx.mood_flow.expire_if_needed(chat_id, now):
        return
    response = ctx.mood_flow.handle_text(chat_id, update.message.text, now)
    if not response:
        return
    await update.message.reply_text(response.text, reply_markup=response.reply_markup)
    if response.completed_payload:
        client = ctx.get_brain_client(context)
        if client:
            await client.post_mood_checkin(response.completed_payload)


async def mood_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("mood_last", update, context.args)
    if not update.message:
        return
    data = await ctx.fetch_mood_last()
    if not data:
        await update.message.reply_text("Brain non disponibile.")
        return
    payload = data.get("data") if isinstance(data, dict) else None
    if not payload:
        await update.message.reply_text("Nessun check-in trovato.")
        return
    message = "🧭 Ultimo check-in\n" + ctx.format_mood_checkin(payload)
    await update.message.reply_text(message)


async def mood_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("mood_week", update, context.args)
    if not update.message:
        return
    data = await ctx.fetch_mood_week(7)
    if not data:
        await update.message.reply_text("Brain non disponibile.")
        return
    aggregates = data.get("aggregates") or {}
    items = data.get("items") or []
    count = int(aggregates.get("count") or 0)
    avg_mood = ctx.format_avg(aggregates.get("avg_mood_score"))
    avg_energy = ctx.format_avg(aggregates.get("avg_energy_level"))
    waste_count = int(aggregates.get("waste_spend_count") or 0)
    lines = [
        "📊 Ultimi 7 giorni",
        f"Check-in: {count} | Mood medio: {avg_mood} | Energia media: {avg_energy} | Spese inutili: {waste_count}",
    ]
    if items:
        lines.extend([f"• {ctx.format_mood_week_line(item)}" for item in items])
    await update.message.reply_text("\n".join(lines))


async def mood_continue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    chat_id = query.message.chat_id
    now = ctx.mood_flow.utcnow()
    if ctx.mood_flow.expire_if_needed(chat_id, now):
        await query.edit_message_reply_markup(reply_markup=None)
        return
    response = ctx.mood_flow.continue_prompt(chat_id)
    if response:
        await query.message.reply_text(response.text, reply_markup=response.reply_markup)
    await query.edit_message_reply_markup(reply_markup=None)


async def mood_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    chat_id = query.message.chat_id
    if ctx.mood_flow.cancel_checkin(chat_id):
        await query.message.reply_text("Check-in annullato.", reply_markup=ReplyKeyboardRemove())
    await query.edit_message_reply_markup(reply_markup=None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("start", update, context.args)
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


async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("spesa", update, context.args)
    if not context.args:
        await update.message.reply_text("Uso: /spesa <importo> <nota opzionale>")
        return
    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Importo non valido. Esempio: /spesa 12.50 pranzo.")
        return
    note = " ".join(context.args[1:]).strip() if len(context.args) > 1 else ""
    category = ctx.user_categories.get(update.effective_user.id)
    message = await ctx.post_expense(amount, note or None, category)
    await update.message.reply_text(message)


async def set_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("categoria", update, context.args)
    if not context.args:
        await update.message.reply_text("Usa /categoria <nome> per impostare la categoria di default.")
        return
    category = " ".join(context.args).strip()
    if not category:
        await update.message.reply_text("Categoria non valida.")
        return
    user_id = update.effective_user.id
    ctx.user_categories[user_id] = category
    await update.message.reply_text(f"Categoria impostata su '{category}'.")


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("chatid", update, context.args)
    chat = update.effective_chat
    if not chat:
        await update.message.reply_text("Non riesco a capire questa chat.")
        return
    await update.message.reply_text(f"chat_id: {chat.id} (tipo: {chat.type})")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("oggi", update, context.args)
    data = await ctx.fetch_summary()
    if not data:
        await update.message.reply_text("Brain non disponibile.")
        return
    expenses_block = ctx.format_expenses_list(data.get("latest", [])[:5])
    await update.message.reply_text(
        f"📅 Oggi ({data['today_date']}): {data['today_total']:.2f}€\n"
        f"Ultime spese:\n{expenses_block}"
    )


async def month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = _require_ctx()
    if await ctx.guard_rate_limit(update):
        return
    ctx.log_command("mese", update, context.args)

    # Decide which month to show: current if no args, else specific month number.
    now = datetime.now(ctx.digest_tz)
    target_month = ctx.parse_month_arg(context.args or [])
    if target_month is None:
        year, month_number = now.year, now.month
    else:
        year, month_number = ctx.month_year_for_arg(target_month, now)

    # Fetch export from start of month and filter client-side.
    since = f"{year}-{month_number:02d}-01"
    expenses = await ctx.fetch_export(since)
    if expenses is None:
        await update.message.reply_text("Brain non disponibile.")
        return
    filtered = ctx.filter_month(expenses, year, month_number)
    await update.message.reply_text(ctx.format_month_report(filtered, year, month_number))
