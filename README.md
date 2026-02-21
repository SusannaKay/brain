# brain-core

Self-hosted Brain core: a FastAPI backend backed by SQLite plus a Telegram bot. Runs well on a Raspberry Pi via Docker Compose.

## What you get
- FastAPI backend with a simple SQLite schema.
- Telegram bot for finance tracking.
- Mood/Energy daily check-in with a low-friction flow and persistent storage in Brain.
- Optional daily digest message.
- Weekly mood digest on Telegram.

## Architecture
- `brain_api/`: FastAPI app + SQLite (`brain_api/data/brain.db`).
- `telegram_bot/`: Telegram bot that calls Brain via HTTP with `X-BRAIN-TOKEN`.
- Brain is the source of truth; the bot never stores final data.

## Requirements
- Docker + Docker Compose
- Telegram bot token (BotFather)
- Shared token for Brain API auth

## Quick start
```sh
cp .env.example .env
# edit .env
docker compose up --build
```

Services:
- `brain-api` on `http://localhost:8000`
- `telegram-bot` runs in the same network and talks to `brain-api`

## Configuration
Copy `.env.example` to `.env` and set:

Core:
- `BRAIN_SHARED_TOKEN` (required)
- `BRAIN_DB_PATH` (default `/app/data/brain.db`)
- `BRAIN_URL` (default `http://brain-api:8000` in compose)
- `TZ` (default `Europe/Rome`)

Telegram bot:
- `TELEGRAM_BOT_TOKEN` (required)
- `BRAIN_TELEGRAM_KEY` (optional, defaults to `BRAIN_SHARED_TOKEN`)
- `BRAIN_BOT_RATE_LIMIT_SECONDS` (default `1.0`)

Digest:
- `DIGEST_ENABLED` (default `false`)
- `DIGEST_TIME` (default `08:00`)
- `DIGEST_CHAT_IDS` (comma-separated chat IDs)
- `WEEKLY_DIGEST_ENABLED` (default `true`)
- `WEEKLY_DIGEST_TIME` (default `20:00`)
- `WEEKLY_DIGEST_WEEKDAY` (default `sun`, accepts `0-6` where `6` is Sunday)

Mood check-in:
- `MOOD_TIME` (default `21:30`, Europe/Rome)
- Uses `DIGEST_CHAT_IDS` for target chats
- `BRAIN_BOT_DB_PATH` (default `/app/data/bot.db`) for bot outbox retry

## API quick reference
Auth: `X-BRAIN-TOKEN` header on protected routes.

- `GET /health`
- `POST /finance/expense`
- `POST /finance/expense/telegram` (auth with `X-TELEGRAM-KEY`)
- `GET /finance/summary`
- `POST /finance/bulk_import`
- `GET /finance/export?since=ISO8601|YYYY-MM-DD`
- `POST /ingest`
- `POST /mood/checkin`
- `GET /mood/last`
- `GET /mood/week?days=7`

Notes:
- `ts` accepts ISO8601 datetime or `YYYY-MM-DD` date.
- `amount` supports positive/negative; zero is rejected.

### Mood check-in payload
```json
{
  "ts": "2026-01-09T07:18:04.076245+00:00",
  "local_date": "2026-01-09",
  "slot": "evening",
  "energy_level": -2,
  "mood_score": -1,
  "mood_text": "optional",
  "did_thing": "optional",
  "waste_spend": true
}
```

## Telegram bot usage
Commands:
- `/start`, `/help`
- `/spesa <importo> <nota opzionale>`
- `/categoria <nome>`
- `/oggi`
- `/mese`
- `/mood` starts a check-in
- `/skip` cancels the current check-in
- `/mood_last` shows the last check-in
- `/mood_week` shows the last 7 days summary

### Mood/Energy flow
1) Energy: keyboard `-2 -1 0 +1 +2`
2) Mood: keyboard `-3 -2 -1 0 +1 +2 +3`
3) Mood text (optional, or "Salta")
4) Did thing (optional, or "Salta")
5) Waste spend: keyboard `Sì/No`

If numeric input is invalid, the bot replies with one line and re-sends the keyboard.

### Scheduling
- Daily prompt at `MOOD_TIME` (default 21:30 Europe/Rome) for chats in `DIGEST_CHAT_IDS`.
- The prompt runs only if the chat is IDLE (no open check-in).
- Open check-ins expire after ~6 hours with no message sent.
- Weekly mood digest at Sunday 20:00 Europe/Rome (see `WEEKLY_DIGEST_*`).

## Finance app sync (event-driven)
- Pull with `GET /finance/export?since=...`, then push with `POST /finance/bulk_import`.
- Deduplication uses a unique key on `(ts, amount_cents, note, category, source)`; replaying is safe.

## Manual smoke test
1) `docker compose up --build`
2) `curl http://localhost:8000/health`
3) Use Telegram `/spesa 10 caffè`
4) `curl -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" http://localhost:8000/finance/summary`

## Compile check
Run a quick syntax check for the API modules:
- `make py-compile`
- or `./scripts/py_compile_check.sh`

## Tests
Install dev deps and run pytest:
- `pip install -r requirements-dev.txt`
- `pytest -q`

## Troubleshooting
- No mood check-ins in DB: finish the flow; check bot logs for outbox queue.
- To query the DB inside the container:
```sh
docker compose exec -T brain-api python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/brain.db")
rows = conn.execute("SELECT id, ts_utc, local_date, slot, energy_level, mood_score, mood_text, did_thing, waste_spend, created_at FROM mood_checkins ORDER BY id DESC LIMIT 10;").fetchall()
for r in rows:
    print(r)
PY
```

## Raspberry Pi notes
- Use a 64-bit Raspberry Pi OS with Docker installed.
- Persist `brain_api/data` for SQLite durability.
- `restart: unless-stopped` is already in compose.
