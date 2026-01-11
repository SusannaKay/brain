import random
from datetime import datetime, timezone
from typing import List, Optional


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
