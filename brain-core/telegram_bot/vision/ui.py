import json
from datetime import datetime
from typing import Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .callbacks import build_callback_data


def render_event_proposal(signal_row) -> Tuple[str, InlineKeyboardMarkup]:
    payload = json.loads(signal_row["payload_json"]) if signal_row["payload_json"] else {}
    title = payload.get("title") or "(senza titolo)"
    start = _format_start(payload.get("start"))
    location = payload.get("location_text") or "(nessun luogo)"
    confidence = _format_confidence(signal_row.get("confidence") if hasattr(signal_row, "get") else signal_row["confidence"])

    text = "\n".join(
        [
            "🧠 Evento rilevato",
            f"Titolo: {title}",
            f"Quando: {start}",
            f"Luogo: {location}",
            f"Confidenza: {confidence}",
        ]
    )

    signal_id = signal_row["id"]
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Crea", callback_data=build_callback_data("A", signal_id))],
            [
                InlineKeyboardButton("✏️ Modifica orario", callback_data=build_callback_data("M", signal_id, "time")),
                InlineKeyboardButton("✏️ Modifica titolo", callback_data=build_callback_data("M", signal_id, "title")),
            ],
            [InlineKeyboardButton("✏️ Modifica luogo", callback_data=build_callback_data("M", signal_id, "location"))],
            [InlineKeyboardButton("❌ Ignora", callback_data=build_callback_data("R", signal_id))],
        ]
    )
    return text, keyboard


def render_place_proposal(signal_row) -> Tuple[str, InlineKeyboardMarkup]:
    payload = json.loads(signal_row["payload_json"]) if signal_row["payload_json"] else {}
    name = payload.get("place_name_text") or payload.get("place_hint") or "(senza nome)"
    address = payload.get("address_text") or "(senza indirizzo)"
    confidence = _format_confidence(signal_row.get("confidence") if hasattr(signal_row, "get") else signal_row["confidence"])

    text = "\n".join(
        [
            "🧠 Luogo rilevato",
            f"Nome: {name}",
            f"Indirizzo: {address}",
            f"Confidenza: {confidence}",
        ]
    )

    signal_id = signal_row["id"]
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Salva", callback_data=build_callback_data("A", signal_id))],
            [InlineKeyboardButton("❌ Ignora", callback_data=build_callback_data("R", signal_id))],
        ]
    )
    return text, keyboard


def _format_start(value: str | None) -> str:
    if not value:
        return "(data/ora sconosciuta)"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def _format_confidence(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"
