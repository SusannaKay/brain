# Vision M1 — Pre-M2 Verification Checklist

## Tests

```sh
cd /Users/susannakayed/Desktop/brain/brain-core
pip install -r requirements-dev.txt
pytest tests/test_vision_callbacks.py tests/test_vision_dao.py tests/test_vision_pipeline.py
```

## Manual Telegram E2E

1) Avvia i servizi:
```sh
cd /Users/susannakayed/Desktop/brain/brain-core
docker compose up --build
```

2) Invia una foto al bot.
   - Atteso: risposta con card "🧠 Evento rilevato" + pulsanti.

3) Premi ✅ Crea.
   - Atteso: messaggio "✅ Evento confermato." e keyboard rimossa.

4) Invia un’altra foto.
   - Premi ❌ Ignora → "❌ Segnale ignorato."

5) Invia un’altra foto.
   - Premi ✏️ Modifica orario → rispondi `18:30`.
   - Atteso: nuova card con orario aggiornato.

Nota: una sola modifica pendente per chat; una nuova modifica sovrascrive la precedente.

## DB inspection (SQLite)

```sh
docker compose exec -T brain-api python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/brain.db")
conn.row_factory = sqlite3.Row

print("\n--- vision_jobs ---")
for r in conn.execute("SELECT id, created_at, status, chat_id, message_id, sha256, trace_id FROM vision_jobs ORDER BY id DESC LIMIT 5"):
    print(dict(r))

print("\n--- vision_signals ---")
for r in conn.execute("SELECT id, job_id, signal_type, action_status, confidence, payload_json FROM vision_signals ORDER BY id DESC LIMIT 5"):
    print(dict(r))

print("\n--- vision_pending_edits ---")
for r in conn.execute("SELECT * FROM vision_pending_edits"):
    print(dict(r))
PY
```

Expected:
- `vision_jobs.status` = `PARSED`
- `vision_signals.action_status` transitions: `PROPOSED` → `APPROVED` → `EXECUTED` after ✅
- `vision_pending_edits` empty after a modify is applied
