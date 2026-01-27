# Brain Vision Module (Telegram Media → Signals → Actions)

## Goal

Implement a privacy-first, **media-effimero** Vision module for Brain:

* User uploads screenshots/media to Telegram.
* System extracts structured **signals** (event/place/payment/ticket/map/chat).
* System proposes actions to the user (human-in-the-loop) and executes on approval.
* **No long-term media storage** (delete files after processing).
* Persist only structured outputs + audit metadata in existing `brain.db`.

## Non-goals (for now)

* No diary text generation.
* No moodboard/inspiration storage.
* No selfie/emotion inference.
* No saving into Google Maps “Saved places” (we store in our DB only).

---

## Architecture Overview

### Pipeline

1. **Telegram ingest**: receive photo/document → download to `/tmp` → compute SHA256 → create `vision_jobs` row.
2. **Vision parse**: call vision model → store `vision_extractions` + one or more `vision_signals`.
3. **Resolvers/Handlers**: based on `signal_type`, create proposals (Telegram message + inline keyboard).
4. **User decision**: approve/modify/reject via callback buttons.
5. **Execute**: on approval, run handler action (e.g., create Google Calendar event; resolve place via Places); persist link tables.
6. **Cleanup**: delete temp media file regardless of success.

### Key Principles

* **Brain stores meaning, not files**: persist JSON payload + sha256 + trace_id.
* **Signal-first**: new features add new `signal_type` + handler.
* **Human-in-the-loop by default**; auto mode only when confidence & fields are strong.

---

## Database (SQLite) — Schema v1

Create/ensure the following tables in `brain.db`:

* `vision_jobs`
* `vision_extractions`
* `vision_signals`
* `places_saved`
* `calendar_links`
* (optional) `oauth_tokens_google`

**SQL**: use the schema from the conversation ("Schema SQLite (brain.db) — v1").

### Naming convention

* `signal_type`: `<category>_candidate.vN` (e.g., `event_candidate.v1`).
* All tables include `created_at` as ISO8601 and `trace_id` for end-to-end correlation.

---

## Signal Types (v1)

Implement these two first:

1. `event_candidate.v1`
2. `place_candidate.v1`

Leave placeholders for future:

* `chat_event_candidate.v1`
* `ticket_candidate.v1`
* `map_screenshot_candidate.v1`
* `payment_screenshot_candidate.v1`
* `receipt_candidate.v1`

---

## Canonical Payloads

### `event_candidate.v1` payload

```json
{
  "title": "string",
  "start": "ISO8601 with tz (Europe/Rome)",
  "end": "ISO8601 with tz (optional)",
  "timezone": "Europe/Rome",
  "location_text": "string (optional)",
  "notes": "string (optional)",
  "source_hint": "flyer|ticket|map|chat|other",
  "place_hint": "string (optional)"
}
```

### `place_candidate.v1` payload

```json
{
  "place_name_text": "string (optional)",
  "address_text": "string (optional)",
  "place_hint": "string",
  "context": {
    "from_map_screenshot": false
  }
}
```

---

## Vision Model Output → Normalization Rules

### Minimal expected model JSON

The vision model can output any rich structure, but the parser MUST normalize into the canonical payloads above.

**Parser responsibilities**:

* Detect if the image likely contains an event or a place.
* Extract text snippets for debugging into `vision_extractions.raw_text`.
* Create 1+ rows in `vision_signals` with:

  * `signal_type`
  * `confidence` (0..1)
  * `payload` (canonical JSON)
  * `proposed_action` (e.g., `create_calendar_event`, `save_place`)
  * `action_status` initially `PROPOSED` if needs confirmation, else `APPROVED` if auto-run is allowed.

**Timezone**: default `Europe/Rome` unless confidently extracted otherwise.

---

## Decision Logic (Human-in-the-loop)

### Always PROPOSE (no auto)

* Missing critical fields:

  * For events: missing `start` date OR missing `title`.
  * For places: missing usable `place_hint`.
* Any `signal_type` derived from chat screenshots in the future.

### Allow auto execute

Only if:

* `confidence >= 0.90`
* Required fields present
* Dedup check passes

---

## Dedup Rules

### Places

* Dedup by `place_provider + place_id` (enforced by UNIQUE index).

### Events

Before creating a calendar event:

* Compare against recent executed event signals:

  * Same day and start time within ±15 minutes AND similar title → treat as duplicate.
* If duplicate suspected: set `action_status=PROPOSED` and message user “sembra già creato”.

---

## Telegram UX Spec

### Callback data format

Keep short:

* Approve: `V1|A|<signal_id>`
* Reject:  `V1|R|<signal_id>`
* Modify:  `V1|M|<signal_id>|<field>` where `<field>` ∈ {`time`,`title`,`location`}

### Proposal messages

#### Event proposal

Text:

* Evento rilevato
* Titolo, data/ora, luogo, confidenza
  Buttons:
* ✅ Crea
* ✏️ Modifica orario
* ✏️ Modifica titolo
* ✏️ Modifica luogo
* ❌ Ignora

#### Place proposal

Text:

* Luogo rilevato
* Nome, indirizzo (se presente), confidenza
  Buttons:
* ✅ Salva
* ❌ Ignora

### Modify flow

On `Modify` button:

* Bot asks user to send new value (e.g., `HH:MM`).
* Store pending edit state (in-memory or DB table `pending_edits`).
* Update `vision_signals.payload` and re-send updated proposal card.

---

## Handlers (v1)

### `places_handler`

Input: `place_candidate.v1`
Steps:

1. Resolve via **Google Places Text Search** (API key).
2. Fetch details (place_id, address, lat/lng).
3. Insert into `places_saved` (dedup by place_id).
4. Mark signal `EXECUTED` or `FAILED`.

### `calendar_handler`

Input: `event_candidate.v1`
Steps:

1. If `place_hint` or `location_text` present: optionally resolve via Places for cleaner location text.
2. Create event via **Google Calendar API v3** (OAuth) with `location` as text.
3. Insert into `calendar_links`.
4. Mark signal `EXECUTED` or `FAILED`.

---

## Error Handling

* Always delete temp media file.
* On failure:

  * `vision_jobs.status=FAILED`
  * store `error_code` + `error_detail`
  * `vision_signals.action_status=FAILED` + `action_error`
* Telegram response: concise error + suggest retry.

---

## Milestones

### M1 (end-to-end skeleton)

* DB schema migration applied.
* Telegram ingest creates `vision_jobs`.
* Vision parse produces dummy signals (hardcoded).
* Proposal messages + callbacks update `action_status`.

### M2 (real vision + real actions)

* Integrate vision model.
* Places handler: resolve + save.
* Calendar handler: create + link.

### M3 (quality)

* Dedup rules.
* Modify flow.
* Confidence thresholds.
* Basic observability logs with `trace_id`.

---

## Codex Agent Task Prompt (copy/paste)

**You are an implementation agent.** Implement M1 then M2 in the Brain codebase.
Constraints:

* Use existing `brain.db`.
* Do not persist media files.
* Implement tables and minimal DAO/repository layer.
* Implement Telegram callback router for `V1|A|id`, `V1|R|id`, `V1|M|id|field`.
* Ensure idempotency via dedup rules.
  Deliverables:
* Migration SQL (or startup-migrate code)
* New module directory `vision/` with parser + handlers
* Tests (minimal) for payload validation and dedup helpers
* README snippet for env vars (Google API key; OAuth credentials)
