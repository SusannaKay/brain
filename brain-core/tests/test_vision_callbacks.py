from telegram_bot.vision.callbacks import parse_callback_data


def test_parse_callback_data() -> None:
    parsed = parse_callback_data("V1|A|123")
    assert parsed is not None
    assert parsed.action == "A"
    assert parsed.signal_id == 123

    parsed = parse_callback_data("V1|M|5|time")
    assert parsed is not None
    assert parsed.action == "M"
    assert parsed.field == "time"

    assert parse_callback_data("V2|A|1") is None
    assert parse_callback_data("V1|M|5|bad") is None
    assert parse_callback_data("V1|R|notanint") is None
