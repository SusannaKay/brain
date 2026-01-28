from dataclasses import dataclass
from typing import Optional


@dataclass
class CallbackData:
    action: str
    signal_id: int
    field: Optional[str] = None


def build_callback_data(action: str, signal_id: int, field: Optional[str] = None) -> str:
    if action not in {"A", "R", "M"}:
        raise ValueError("Invalid action")
    if action == "M":
        if field not in {"time", "title", "location"}:
            raise ValueError("Invalid field")
        data = f"V1|{action}|{signal_id}|{field}"
    else:
        data = f"V1|{action}|{signal_id}"
    if len(data.encode("utf-8")) > 64:
        raise ValueError("Callback data too long")
    return data


def parse_callback_data(data: str) -> Optional[CallbackData]:
    if not data:
        return None
    parts = data.split("|")
    if len(parts) < 3:
        return None
    if parts[0] != "V1":
        return None
    action = parts[1]
    if action not in {"A", "R", "M"}:
        return None
    try:
        signal_id = int(parts[2])
    except ValueError:
        return None
    field = None
    if action == "M":
        if len(parts) != 4:
            return None
        field = parts[3]
        if field not in {"time", "title", "location"}:
            return None
    return CallbackData(action=action, signal_id=signal_id, field=field)
