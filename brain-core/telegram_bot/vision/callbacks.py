from dataclasses import dataclass
from typing import Optional


@dataclass
class CallbackData:
    action: str
    signal_id: int
    field: Optional[str] = None


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
