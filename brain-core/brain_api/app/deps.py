from fastapi import Depends

from .db import get_connection
from .settings import Settings, get_settings


def get_db(settings: Settings = Depends(get_settings)):
    yield from get_connection(settings.db_path)
