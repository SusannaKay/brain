from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger("brain-telegram-bot.brain-client")


class BrainClient:
    def __init__(self, base_url: str, token: str, db_path: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mood_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                """
            )

    async def post_mood_checkin(self, payload: dict) -> bool:
        headers = {"X-BRAIN-TOKEN": self.token}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.base_url}/mood/checkin", json=payload, headers=headers)
                resp.raise_for_status()
            logger.info("Mood check-in posted successfully.")
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("Mood check-in failed: status=%s body=%s", exc.response.status_code, exc.response.text)
            self._enqueue(payload, f"HTTP {exc.response.status_code}")
        except httpx.RequestError as exc:
            logger.error("Mood check-in failed: %s", exc)
            self._enqueue(payload, str(exc))
        return False

    async def retry_due(self) -> int:
        now = _utcnow()
        rows = self._fetch_due(now)
        if not rows:
            return 0
        success = 0
        for row in rows:
            payload = json.loads(row["payload_json"])
            ok = await self._post_payload(payload)
            if ok:
                self._delete_row(row["id"])
                success += 1
            else:
                self._mark_failed(row["id"], row["attempts"], "retry failed", now)
        return success

    async def _post_payload(self, payload: dict) -> bool:
        headers = {"X-BRAIN-TOKEN": self.token}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.base_url}/mood/checkin", json=payload, headers=headers)
                resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Retry mood check-in failed: %s", exc)
            return False

    def _enqueue(self, payload: dict, error: str) -> None:
        now = _utcnow()
        next_attempt = now + _backoff_delay(0)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO mood_outbox (payload_json, created_at, next_attempt_at, attempts, last_error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    json.dumps(payload, ensure_ascii=False),
                    now.isoformat(),
                    next_attempt.isoformat(),
                    0,
                    error[:500],
                ),
            )
            conn.commit()
        logger.info("Mood check-in queued in outbox; next_attempt_at=%s", next_attempt.isoformat())

    def _fetch_due(self, now: datetime) -> List[sqlite3.Row]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT id, payload_json, attempts
                FROM mood_outbox
                WHERE next_attempt_at <= ?
                ORDER BY id ASC
                LIMIT 5
                """,
                (now.isoformat(),),
            ).fetchall()

    def _mark_failed(self, row_id: int, attempts: int, error: str, now: datetime) -> None:
        next_attempt = now + _backoff_delay(attempts + 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE mood_outbox
                SET attempts = ?, last_error = ?, next_attempt_at = ?
                WHERE id = ?
                """,
                (attempts + 1, error[:500], next_attempt.isoformat(), row_id),
            )
            conn.commit()

    def _delete_row(self, row_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM mood_outbox WHERE id = ?", (row_id,))
            conn.commit()


async def retry_loop(client: BrainClient, interval_seconds: int = 60) -> None:
    while True:
        try:
            await client.retry_due()
        except Exception:
            logger.exception("Unexpected error in mood outbox retry loop.")
        await _sleep(interval_seconds)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _backoff_delay(attempts: int) -> timedelta:
    seconds = min(3600, 30 * (2**attempts))
    return timedelta(seconds=seconds)


async def _sleep(seconds: int) -> None:
    import asyncio

    await asyncio.sleep(seconds)
