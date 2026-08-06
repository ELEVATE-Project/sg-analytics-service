# RAG Implementation Pipeline
Semantic matching service that pairs community **challenges** with the most relevant **solutions** using vector embeddings, Qdrant, and Gemini LLM validation.

---

## Architecture Overview

```
CSV Data
   └── matching_store.py (one-time ingestion)
              │  embeddings + scores
              ▼
       Qdrant Vector DB  (collection: matching_store)
              │
              ▼
   FastAPI Server  (app/)
     ├── CORS origin-guard middleware
     ├── GET /api/v1/voices/animations
     │      ├── In-memory TTL cache
     │      ├── Greedy diversity selection (Qdrant scroll)
     │      ├── 1:1 solution pairing (Qdrant ANN search)
     │      └── Gemini LLM pair validation
     └── JSON response  →  Frontend
```

**Stack:** Python · FastAPI · Qdrant · `all-MiniLM-L6-v2` · Google Gemini (`gemini-flash-latest`) · `python-dotenv`

---

## Repository Structure

```
rag-implementation/
├── app/
│   ├── main.py                    # FastAPI app, CORS, Logging startup
│   ├── config.py                  # Centralised settings (reads from .env)
│   ├── logging_config.py          # Structured app & access logs
│   ├── api/
│   │   ├── routes/
│   │   │   └── animations.py      # GET /api/v1/voices/animations endpoint
│   │   └── models/
│   │       └── schemas.py         # Pydantic models (PairJudgement, ValidationResponse)
│   ├── services/
│   │   ├── matching_service.py    # Core pairing logic + TTL cache + retry fallback
│   │   ├── qdrant_service.py      # Qdrant queries (scroll + ANN search)
│   │   └── llm_service.py         # Gemini LLM validation
│   └── database/
│       └── database.py            # QdrantClient singleton
├── matching_store.py              # One-time data ingestion & scoring pipeline
├── data/                          # CSV source files (challenges + solutions)
├── logs/                          # Auto-rotated application and access logs
├── pre_llm_logs/                  # Debug JSONL logs written before LLM call
├── .env.example                   # Reference config (copy → .env)
├── requirements.txt
└── README.md
```

---

## 1. Data Ingestion & Scoring (`matching_store.py`)

Run **once** whenever you receive new CSV data or want to rebuild the database.

### Workflow

| Step | What happens |
|------|-------------|
| **Load** | Reads all CSV files matching `CHALLENGES_GLOB` and `SOLUTIONS_GLOB` from `DATA_DIR`. Multiple state/sheet files are auto-discovered and merged. |
| **Embed** | Converts every challenge and solution statement into a 384-dim vector using `all-MiniLM-L6-v2` (batched, configurable via `BATCH_SIZE`). |
| **Score challenges** | Temporarily upserts solutions → queries top-5 solutions per challenge → averages their cosine scores → stores as `embedded_score` on each challenge point. |
| **Score solutions** | Reverses the process: queries top-5 challenges per solution → saves average as `embedded_score` on each solution point. |
| **Final upsert** | Persists all challenge and solution points into the Qdrant collection with full payload (statement, metadata, embedded_score, type). |

> **ID collision prevention:** Challenges use `CHALLENGE_ID_OFFSET=0`, solutions use `SOLUTION_ID_OFFSET=10000000` — both share the same collection without ever colliding.

```bash
python matching_store.py
```

---

## 2. FastAPI Server (`app/`)

### Starting the server

```bash
uvicorn app.main:app --reload --port 8000
```

### Endpoint

```
GET /api/v1/voices/animations?limit=20&reset=false
```

| Query param | Default | Description |
|-------------|---------|-------------|
| `limit` | `FINAL_RESULT_SIZE` (20) | Number of pairs to return |
| `reset` | `false` | Clears cache + used-sets; starts fresh from the beginning |

**Response shape:**
```json
{
  "data": [
    {
      "rank": 1,
      "match_score": 0.9123,
      "challenge": { "id": "...", "text": "...", "role": "...", "district": "...", "state": "..." },
      "solution":  { "id": "...", "text": "...", "role": "...", "district": "...", "state": "..." }
    }
  ]
}
```

### Pairing Logic (`matching_service.py`)

1. **TTL Cache** — Returns the cached result for `CACHE_TTL_HOURS` (default 2 h) up to the requested `limit`. Resets on process restart or `?reset=true`.
2. **Fetch challenges** — Scrolls Qdrant ordered by `embedded_score DESC`, skipping already-used challenge IDs. Topic capping (`MAX_PER_TOPIC=1`) prevents over-representing any single topic (e.g. Aadhaar).
3. **Greedy diversity** — Selects the `PRE_LLM_FETCH_SIZE` most **mutually dissimilar** challenges using cosine distance maximisation, ensuring broad topic variety.
4. **1:1 pairing & Fallback** — For each challenge, fetches the top `TOP_SOLUTIONS_PER_CHALLENGE` solutions via ANN search using `MIN_MATCH_SCORE`. **If 0 solutions are found, it immediately retries** with a lower `FALLBACK_MATCH_SCORE` (progressive relaxation).
5. **Bot Type Filter** — The `SOLUTION_BOT_TYPE` env controls whether solutions fetched are restricted to `story`, `discussion`, or `hybrid` (both).
6. **LLM validation** (`llm_service.py`) — Sends all candidate pairs to `gemini-flash-latest` in a single structured call. Pairs are rejected if: score < 4, PII detected (person name / village / address / phone), grammar is garbled (>10%), solution doesn't address the challenge's specific root cause, or either text is just a question.
7. **Lock used IDs** — Challenge and solution IDs are added to in-memory `used_challenges` / `used_solutions` sets, guaranteeing no repeats across cache cycles.
8. **Pagination** — Once the cache is exhausted or reset, the system automatically fetches the **next batch** of unseen pairs, picking up exactly where the last cycle ended.

---

## 3. CORS / Origin Security (`app/main.py`)

**No API keys are used.** Access control is enforced entirely via an **origin allowlist** configured in `.env`.

### How it works

```
ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com   ← .env
         │
         ▼
config.py → Settings.ALLOWED_ORIGINS  (comma-split, stripped list)
         │
         ▼
main.py
 ├── CORSMiddleware
 │     allow_origins   = settings.ALLOWED_ORIGINS
 │     allow_methods   = settings.ALLOWED_METHODS    (GET, POST, OPTIONS)
 │     allow_headers   = settings.ALLOWED_HEADERS    (Content-Type, Authorization)
 │     allow_credentials = True  (False when wildcard * is used)
 │
 └── origin_guard  (custom HTTP middleware, runs on every request)
       ├── Wildcard (*) → skip guard, pass through immediately
       ├── No Origin header → pass through (server-to-server / curl)
       └── Origin NOT in list → 403 Forbidden
                { "error": "Forbidden", "detail": "Origin '...' is not in the allowed origins list." }
```

### Configuration

Edit `.env` (or set environment variables):

```env
# Comma-separated list of allowed browser origins
ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com

# For local development
# ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173

# Wildcard (dev only — disables credentials)
# ALLOWED_ORIGINS=*

ALLOWED_METHODS=GET,POST,OPTIONS
ALLOWED_HEADERS=Content-Type,Authorization
```

> No server restart is needed if you pass env vars directly; a restart is required when reading from `.env`.

---

## 4. Configuration Reference (`app/config.py`)

All settings are read from environment variables (`.env` file at project root).

| Variable | Default | Description |
|---|---|---|
| `QDRANT_HOST` | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | `6333` | Qdrant server port |
| `MATCHING_COLLECTION` | `matching_store` | Qdrant collection name |
| `FINAL_RESULT_SIZE` | `20` | Pairs returned per API call |
| `PRE_LLM_FETCH_SIZE` | `40` | Candidate pairs fetched before LLM validation |
| `TOP_SOLUTIONS_PER_CHALLENGE` | `50` | ANN results per challenge |
| `SOLUTION_BOT_TYPE` | `hybrid` | Filter solution `bot_type`: `story`, `discussion`, or `hybrid` |
| `CACHE_TTL_HOURS` | `2.0` | In-memory cache lifetime (hours) |
| `MAX_PER_TOPIC` | `1` | Max challenges per deduplicated topic |
| `MIN_MATCH_SCORE` | `0.85` | Primary lower bound of preferred score band |
| `MAX_MATCH_SCORE` | `0.99` | Upper bound of preferred score band |
| `FALLBACK_MATCH_SCORE`| `0.70` | Retry threshold used if primary fetch yields 0 solutions |
| `GEMINI_API_KEY` | _(empty)_ | Google Gemini API key; LLM step skipped if blank |
| `DEBUG_LOG_DIR` | `pre_llm_logs/` | Directory for pre-LLM JSONL debug logs |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins |
| `ALLOWED_METHODS` | `GET,POST,OPTIONS` | Allowed HTTP methods |
| `ALLOWED_HEADERS` | `Content-Type,Authorization` | Allowed request headers |
| `RATE_LIMIT`      | `10/minute` | Rate limit per IP address |
| `LOG_LEVEL` | `INFO` | Application log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `LOG_DIR` | `logs` | Directory for auto-rotated log files |
| `LOG_RETENTION_DAYS`| `7` | How many daily log files to retain |

---

## 5. Logging

The application uses standard Python logging out of the box with the following features:
- **Console Logs**: Prints to standard output (terminal).
- **Auto-Rotating File Logs**: Writes daily logs to the `logs/` directory (ignored by git).
- **Separation**: App/Error logs are written to `logs/app.log`, while Uvicorn HTTP access logs go to `logs/access.log`.
- **Retention**: Keeps 7 days of logs automatically.

Check logs live with:
```bash
tail -f logs/app.log
```

---

## 5. Setup & Running

### Prerequisites

- Python 3.10+
- Qdrant running locally (`docker run -p 6333:6333 qdrant/qdrant`)

### Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env — set GEMINI_API_KEY, ALLOWED_ORIGINS, etc.
```

### Ingest data (first time / new data)

```bash
python matching_store.py
```

### Start API server

```bash
uvicorn app.main:app --reload --port 8000
```

### Test the endpoint

```bash
curl http://127.0.0.1:8000/api/v1/voices/animations
```

---

## 6. Debug Logs

Before each LLM validation call, a timestamped `.jsonl` file is written to `pre_llm_logs/`. Each line is a JSON object containing:
- Challenge details (id, text, district, state, embedded_score)
- Top-5 candidate solutions with scores
- The selected (mapped) solution

These logs are useful for inspecting pairing decisions without waiting for LLM output.
