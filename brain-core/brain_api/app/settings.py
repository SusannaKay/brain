import os
from functools import lru_cache
from typing import Optional


class Settings:
    def __init__(self) -> None:
        self.db_path: str = os.getenv("BRAIN_DB_PATH", "/app/data/brain.db")
        self.shared_token: str = os.getenv("BRAIN_SHARED_TOKEN", "")
        self.telegram_key: str = os.getenv("BRAIN_TELEGRAM_KEY") or self.shared_token
        self.timezone: str = os.getenv("TZ", "Europe/Rome")
        if not self.shared_token:
            raise RuntimeError("BRAIN_SHARED_TOKEN must be set")
        if not self.telegram_key:
            raise RuntimeError("BRAIN_TELEGRAM_KEY must be set")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
