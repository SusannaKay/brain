from fastapi import Depends, Header, HTTPException, status

from .settings import Settings, get_settings


def verify_brain_token(
    settings: Settings = Depends(get_settings),
    token: str = Header(..., alias="X-BRAIN-TOKEN"),
) -> str:
    if token != settings.shared_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid brain token")
    return token


def verify_telegram_key(
    settings: Settings = Depends(get_settings),
    key: str = Header(..., alias="X-TELEGRAM-KEY"),
) -> str:
    if key != settings.telegram_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid telegram key")
    return key
