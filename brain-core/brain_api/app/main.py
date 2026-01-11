import logging
import time as time_module
from typing import Dict

from fastapi import FastAPI, Request

from .db import init_db
from .routers import events_router, finance_router, mood_router
from .settings import get_settings

app = FastAPI(title="Brain API", version="1.0.0")
logger = logging.getLogger("brain-api")

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time_module.perf_counter()
    logger.info(
        "request start method=%s path=%s client=%s",
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown",
    )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request error method=%s path=%s", request.method, request.url.path)
        raise
    duration_ms = (time_module.perf_counter() - start) * 1000
    logger.info(
        "request end method=%s path=%s status=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        getattr(response, "status_code", "unknown"),
        duration_ms,
    )
    return response


@app.on_event("startup")
def on_startup() -> None:
    settings = get_settings()
    init_db(settings.db_path)


@app.get("/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


app.include_router(finance_router)
app.include_router(mood_router)
app.include_router(events_router)
