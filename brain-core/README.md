# brain-core

Self-hosted Brain core composed of a FastAPI backend with SQLite storage and a Telegram bot client. Designed to run on a Raspberry Pi via Docker Compose.

## Prerequisites
- Docker and Docker Compose
- Telegram bot token (create via BotFather)
- Secrets in a `.env` file (see `.env.example`)

## Configuration
Copy `.env.example` to `.env` and set required values:
- `TELEGRAM_BOT_TOKEN`: token from BotFather
- `BRAIN_SHARED_TOKEN`: shared auth token for protected API routes
- `BRAIN_TELEGRAM_KEY`: internal header secret used by the Telegram bot when posting expenses
- `BRAIN_URL`: brain-api URL (default works in Docker network)
- `BRAIN_DB_PATH`: SQLite path (default `/app/data/brain.db`)
- `TZ`: timezone for summaries (default `Europe/Rome`)
- `BRAIN_BOT_RATE_LIMIT_SECONDS`: throttle between user commands (default `1.0`)
- `DIGEST_ENABLED`: enable the daily digest sender (default `false`)
- `DIGEST_TIME`: HH:MM in `Europe/Rome` when the digest goes out
- `DIGEST_CHAT_IDS`: comma-separated Telegram chat IDs that should receive the digest (required when enabled)

## Running with Docker Compose
```sh
cp .env.example .env
# edit .env with your secrets

docker compose up --build
```
Services:
- brain-api exposed on `http://localhost:8000`
- telegram-bot runs without exposed ports and talks to brain-api internally

## API quick reference
- `GET /health`
- `POST /finance/expense` (header `X-BRAIN-TOKEN`)
- `POST /finance/expense/telegram` (header `X-TELEGRAM-KEY` from bot)
- `GET /finance/summary` (header `X-BRAIN-TOKEN`)
- `POST /finance/bulk_import` (header `X-BRAIN-TOKEN`)
- `GET /finance/export?since=ISO8601|YYYY-MM-DD` (header `X-BRAIN-TOKEN`)
- `POST /ingest` (header `X-BRAIN-TOKEN`)
Notes:
- `ts` fields accept ISO8601 datetimes or `YYYY-MM-DD` dates (dates become midnight UTC).
- `amount` fields can be positive (income) or negative (expense); zero is rejected.

## Integrating FinanceApp (event-driven)
- FinanceApp may be offline; treat sync as opportunistic. When the user opens FinanceApp, it should first pull from `GET /finance/export?since=...`, then push pending writes to `POST /finance/bulk_import`.
- Deduplication is handled server-side via a unique key on `(ts, amount_cents, note, category, source)` with `INSERT OR IGNORE`, so replaying past items is safe.
- Suggested flow: track the last successful export timestamp locally. On app open, call export with that timestamp, merge results into the local store, then send any unsynced local expenses via `bulk_import`. Update the local watermark only after both directions succeed.
- First sync: if no local watermark exists, call `GET /finance/export?since=1970-01-01` (date-only is accepted).
- Conflict handling: if the same logical expense exists locally and remotely with different fields, prefer the latest `ts` as the winner and re-send it in `bulk_import`; older duplicates will be ignored by the server. If amounts differ for the same `ts`, treat it as an edit and push a new item with a distinct timestamp or source to avoid collision.

### Curl examples
```sh
# health
curl http://localhost:8000/health

# create expense
curl -X POST http://localhost:8000/finance/expense \
  -H "Content-Type: application/json" \
  -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" \
  -d '{"amount": 12.5, "note": "pranzo", "category": "cibo"}'

# summary
curl -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" http://localhost:8000/finance/summary

# export since timestamp
curl -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" \
  "http://localhost:8000/finance/export?since=2024-01-01T00:00:00Z"
```

## Telegram bot usage
Commands:
- `/start`, `/help`
- `/spesa <importo> <nota opzionale>`
- `/categoria <nome>` sets default category for the user (kept in memory)
- `/oggi` shows today total
- `/mese` shows month total

If brain-api is unreachable, the bot replies with a friendly error.

Daily digest (when enabled with `DIGEST_ENABLED=true`) sends one message per day to the configured chats with:
- Totale di oggi e del mese
- Top categorie di oggi (se presenti)
- Una breve riga “oracolo” un po' sarcastica
The schedule uses an internal async loop; no external scheduler is needed.

## Manual smoke test
1. Bring up services: `docker compose up --build`.
2. Check API health: `curl http://localhost:8000/health` -> `{ "ok": true }`.
3. Add an expense via bot `/spesa 10 caffè` or via curl.
4. Fetch summary: `curl -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" http://localhost:8000/finance/summary`.
5. Restart containers to ensure data persists in `./brain_api/data/brain.db`.

## Raspberry Pi notes
- Use a 64-bit Raspberry Pi OS with Docker installed.
- Map `./brain_api/data` to persist the SQLite file on SD or external storage.
- Keep `docker compose` running with a systemd service or `restart: unless-stopped` (already configured).
