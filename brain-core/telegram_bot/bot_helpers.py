from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _build_continue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Continua", callback_data="mood_continue"),
                InlineKeyboardButton("Annulla", callback_data="mood_cancel"),
            ]
        ]
    )
