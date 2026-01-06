# Finance Sync Contract

This document describes the HTTP contract between FinanceApp and `brain-api` for export/import sync.

## Authentication
- Header `X-BRAIN-TOKEN` is required on every endpoint below.
- Tokens are compared verbatim against `BRAIN_SHARED_TOKEN` (see `.env`); mismatches return `401`.

## Endpoints

### GET /finance/export
- Purpose: Fetch expenses recorded since a given timestamp (inclusive, ascending).
- Query: `since` (ISO8601 timestamp or `YYYY-MM-DD` date, any timezone; converted to UTC internally).
- Response: `200 OK` with a JSON array of expense objects.

Expense object fields:
- `ts` (string, ISO8601 UTC)
- `amount` (number, two-decimal precision)
- `note` (string|null)
- `category` (string, defaults to `"uncategorized"` if empty)
- `source` (string, may be empty)

Example:
```sh
curl -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" \
  "http://localhost:8000/finance/export?since=2024-01-01T00:00:00Z"
```
For a first sync with no stored watermark, you can start from the epoch:
```sh
curl -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" \
  "http://localhost:8000/finance/export?since=1970-01-01"
```
Response:
```json
[
  {
    "ts": "2024-04-15T08:30:00+00:00",
    "amount": 12.5,
    "note": "cappuccino",
    "category": "cibo",
    "source": "telegram"
  },
  {
    "ts": "2024-04-15T12:05:00+00:00",
    "amount": 18,
    "note": "pranzo",
    "category": "cibo",
    "source": ""
  }
]
```

### POST /finance/bulk_import
- Purpose: Insert a batch of expenses, deduplicating by content.
- Body: JSON array of expense items.
- Response: `200 OK` with `{"inserted": <int>, "received": <int>}`.

Request item fields (all validated with FastAPI/Pydantic):
- `ts` (ISO8601 timestamp **or** `YYYY-MM-DD` date, required; dates are interpreted as midnight UTC)
- `amount` (number != 0, required; rounded to 2 decimals, stored as cents; positive for income, negative for expenses)
- `note` (string|null, optional)
- `category` (string|null, optional; empty becomes `"uncategorized"` in reads)
- `source` (string|null, optional; empty defaults to `"bulk"`)

Example:
```sh
curl -X POST http://localhost:8000/finance/bulk_import \
  -H "Content-Type: application/json" \
  -H "X-BRAIN-TOKEN: $BRAIN_SHARED_TOKEN" \
  -d '[
    {
      "ts": "2024-04-15",
      "amount": -12.5,
      "note": "cappuccino",
      "category": "cibo",
      "source": "finance-app"
    },
    {
      "ts": "2024-04-15T12:05:00Z",
      "amount": 18.0,
      "note": "pranzo",
      "category": "cibo"
    }
  ]'
```
Possible response:
```json
{"inserted": 2, "received": 2}
```

## Deduplication rules
- Unique key: `(ts, amount_cents, note, category, source)`.
- Inserts use `INSERT OR IGNORE`; duplicates are skipped without error.
- Amounts are rounded to two decimals before converting to cents for the unique key.
- Blank/whitespace-only `note`, `category`, or `source` are normalized to empty strings before deduping.
