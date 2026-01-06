# Security Notes

- **Tokens**: `X-BRAIN-TOKEN` (set via `BRAIN_SHARED_TOKEN`) secures all finance and ingest endpoints. `X-TELEGRAM-KEY` (`BRAIN_TELEGRAM_KEY`) is only for the Telegram expense endpoint. Tokens are compared verbatim; wrong values return `401`.
- **Transport**: The stack assumes traffic stays on the Docker/local network (e.g., compose bridge or LAN). If exposed beyond the trusted network, place `brain-api` behind TLS and restrict inbound IPs.
- **Secrets handling**: Keep `.env` out of version control. Distribute tokens out-of-band and rotate if leaked. Avoid logging tokens; the app only logs method/path/status/latency.
- **Persistence**: SQLite lives at `BRAIN_DB_PATH` (default `/app/data/brain.db` on a mapped volume). Ensure filesystem permissions prevent other hosts/users from reading it when mounted.
- **Least access**: Give FinanceApp only the `X-BRAIN-TOKEN`; do not share the Telegram key or internal headers with clients.
