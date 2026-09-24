# SAULI prototype

Development prototype of **SAULI: Secure Automated Unit for Lost Items**, for the
LSPU San Pablo City campus lost-and-found thesis. Two primary pages:

- `/station`: follow a sequential kiosk flow for side-one/side-two capture, found
  location entry, identification, and private storage through FastAPI and Ollama.
- `/retrieve`: describe a lost item, provide last-seen details, review real ranked
  candidates, and complete a clearly simulated retrieval.

The root route redirects to `/station`. There are no built-in successful sample
records. Real ingestion/search require both services; missing services return
useful errors. Fixtures appear only in tests.

## Architecture and responsibilities

```text
Next.js /station and /retrieve
                 |
                 v
FastAPI: validation, server timestamps, safe API responses
         |                          |
         v                          v
Local Ollama / Qwen          Supabase Postgres + private Storage
  found_item_vision.py      items, images, searches, score audit,
  two-view inspection       atomic retrieval + event log
```

`backend/app/services/found_item_vision.py` contains the detailed two-view prompt
and Ollama request construction, including front/back order, separated `[img]`
markers, `think=False`, component counting, damage inspection, and extraction
summary. It accepts uploaded bytes, with no fixed filenames required by the API.
The Pydantic-generated JSON Schema constrains Ollama's response before the same
model validates and safely normalizes bounded text-shape variations. Blocking
Ollama calls run in the FastAPI threadpool; invalid JSON/schema receives at most
one repair retry. If final JSON lands in `thinking`, only the validated structured
object is used. Raw responses and chain-of-thought are never persisted by the API.

The thesis responsibilities remain distinct:

| Responsibility | This prototype |
| --- | --- |
| Low-level image processing | Pillow validates content/dimensions; planned OpenCV quality checks are not yet integrated |
| Semantic recognition | Qwen extracts visible names, attributes, components, condition, and uncertainty |
| Similarity matching | Deterministic feature scoring + Qwen reranking; embeddings and pgvector remain future work |
| Security and retrieval | Backend/database state rules; QR, scan, compartment, and removal are explicitly simulated |

AI output does not prove ownership or authorize real hardware.

## Repository

```text
frontend/
  app/station/            Desktop/mobile ingestion page
  app/retrieve/           Retriever page with internal screen states
  components/            Accessible forms, results and simulation components
  lib/                   API client, types and date helpers
  public/                Static prototype assets
  .env.local.example     Public API address only
backend/
  app/api/               FastAPI routes
  app/core/              Settings and safe errors
  app/models/            Pydantic AI/API models
  app/services/          Ollama prompts, matching, images and Supabase integration
  tests/                 Automated logic/API tests
  .env.example           Empty credential placeholders
supabase/
  migrations/            Unchanged copy of the authoritative reset
  verify.sql             Rollback-only SQL checks
  tests/                 Embedded PostgreSQL verification harness
SAULI_Anonymous_Reset.sql Authoritative destructive SAULI reset
requirements.txt         Minimal Ollama client dependency list
```

The supplied `SAULI_Anonymous_Reset.sql` is authoritative. Its migration copy is
byte-for-byte identical; application code does not run it automatically. No usable
web 3D model or named close-up PNG was present.
The station intake uses a code-native kiosk interface and does not display the
cabinet/container render. Reference screenshots and personal profile photos are
not embedded as the interface.

## Prerequisites

- Node.js **22+**, npm (tested with Node 24).
- Python **3.11+** (tested with Python 3.14); use a virtual environment.
- Ollama with enough RAM/VRAM for the selected vision model.
- A Supabase development project and a **newly rotated backend secret key**.

Frontend versions are locked in `frontend/package-lock.json`. Python dependency
bounds are in `backend/requirements.txt`.

## 1. Ollama

Run on the inference computer:

```powershell
ollama pull qwen3.5:9b-q8_0
ollama list
```

Start Ollama's desktop application or `ollama serve`. The backend defaults to
`http://127.0.0.1:11434`. Set `OLLAMA_MODEL` to another installed vision model, such
as `qwen3-vl:8b`, if desired. Model changes can affect accuracy/schema reliability.

For a separate GPU computer over Tailscale, set backend `OLLAMA_HOST` to that
computer's private address and Ollama port. Configure Ollama's listening interface
and the host firewall/Tailscale rules to allow the backend connection. Only
FastAPI contacts Ollama; do not expose unauthenticated Ollama publicly. No
machine-specific Tailscale address is included in configuration examples.

## 2. Supabase

Use a development project. Rotate any previously shared credential and do not
reuse values from chat history.

1. Back up any prior SAULI data, then run `SAULI_Anonymous_Reset.sql` in the
   Supabase SQL Editor as project administrator. **This deletes and rebuilds the
   four prior SAULI prototype tables.** It does not drop the public schema, change
   Supabase Auth, or touch unrelated project tables. The identical migration copy
   is `supabase/migrations/202609230001_sauli_anonymous_reset.sql`.
2. Confirm `found_items`, `search_requests`, `match_results`, `retrieval_events`,
   and the **private** `sauli-item-images` bucket exist. The reset also creates
   indexes, item-code generation, timestamps, temporal eligibility and retrieval
   functions, RLS, and explicit privilege restrictions.
3. Run `supabase/verify.sql` for rollback-only verification. Read
   [supabase/README.md](supabase/README.md) for the full schema/test details.
4. Put the project URL and a newly generated secret key in `backend/.env` only.
   Prefer the current `sb_secret_...` format to legacy service-role JWTs.

An earlier working file contained a real legacy service-role credential. Its value
has been removed, but it must be revoked/rotated in Supabase before this project is
used. Never reuse a key copied from source, chat, screenshots, or history.

The reset never removes Storage objects. If the old `found-item-images` bucket
contains test files, empty and delete it through the Supabase Storage Dashboard or
Storage API—not SQL. New uploads use only `sauli-item-images`.

The browser never receives the Supabase secret. RLS and table/RPC grants deny
anonymous/authenticated direct access. FastAPI uses the privileged service role.
Storage paths, such as `found-items/<uuid>/front.jpg` and
`searches/<uuid>/query.jpg`, are persisted instead of public URLs. FastAPI returns
short-lived signed image URLs; these grant access for their lifetime. Failed
ingestion attempts best-effort cleanup of its new uploads.

## 3. Backend

Copy `backend/.env.example` to `backend/.env`, then enter rotated credentials:

```dotenv
SUPABASE_URL=
SUPABASE_SECRET_KEY=
SUPABASE_STORAGE_BUCKET=sauli-item-images
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b-q8_0
FRONTEND_ORIGIN=http://localhost:3000
APP_TIMEZONE=Asia/Manila
MATCH_MIN_SCORE=45
MATCH_LIMIT=5
DETERMINISTIC_SHORTLIST_LIMIT=10
AI_RERANK_LIMIT=5
SIGNED_URL_TTL_SECONDS=900
MAX_IMAGE_BYTES=10485760
```

Real `.env` files are ignored by Git. No actual credentials are supplied. CORS
allows the configured frontend origin. Authentication is outside this prototype:
run on a trusted development computer/network; CORS alone is not authorization.

Windows PowerShell, starting at the repository root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If activation is blocked, use `.\.venv\Scripts\python.exe` in place of `python`.

macOS/Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use `--host 0.0.0.0` only when intentionally testing from other trusted devices.
`http://localhost:8000/health` reports dependency status without exposing secrets.
Interactive API docs are at `http://localhost:8000/docs`.

If Qwen returns invalid structured data, the backend terminal prints a safe
validation diagnostic such as the schema name, attempt number, response field,
response lengths, missing required fields, and failing Pydantic field/error types.
It deliberately does not print the raw model response, image data, personal
information, or chain-of-thought. Keep the backend terminal visible while testing.

## 4. Frontend

Copy `frontend/.env.local.example` to `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

If PowerShell blocks `npm.ps1`, use `npm.cmd install` and `npm.cmd run dev`.
Open `http://localhost:3000/station` or `http://localhost:3000/retrieve`.
For a phone, change the API URL to the development computer's address (not the
phone's `localhost`) and set `FRONTEND_ORIGIN` to the exact frontend origin.
Restart processes after environment changes.

## API and behavior

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Safe API, database, Storage and Ollama status |
| `POST /api/found-items/analyze` | Analyze two validated images without uploading or saving them |
| `POST /api/found-items/reconcile-review` | Reconcile a finder-edited summary with all related searchable attributes without writing data |
| `POST /api/found-items/confirm-and-store` | Save finder-reviewed details and images after explicit confirmation |
| `POST /api/matches/search` | Lost-item details, anonymous session/idempotency UUIDs, optional query image |
| `GET /api/found-items/{id}` | Validated details and signed front/back previews |
| `POST /api/retrievals/{id}/simulate` | Search/session-bound atomic retrieval and event |

Station images must be valid JPEG/PNG/WebP, at most 10 MiB each. Both are required.
The server records `found_at` by default. The station page also has an optional,
clearly labeled developer control that can override the found date/time for
prototype testing. The override is converted from Asia/Manila to timezone-aware
UTC before storage and is not intended for production operator use.

Analysis is a draft-only operation: it performs no Storage upload or database
insert. The finder reviews and may correct the visible item fields in the station
UI before confirming. If the finder changes the searchable summary, SAULI first
reconciles that correction with the related structured attributes and returns the
complete result for another human review. Confirmation remains disabled until the
summary and attributes are synchronized. The final flat columns, `analysis_json`,
and `search_document` are all rebuilt from that one confirmed analysis object.
Reconciliation itself performs no Storage or database write.

Confirmation requests use `Accept: text/event-stream` for actual `uploading`,
`saving`, and `complete` events; other clients get normal JSON. Failures during a
stream send an error event with a status, while ordinary requests use standard
HTTP errors. The station shows simple progress messages and elapsed time and
disables duplicate submissions. After a lost connection, verify whether a
confirmation completed before resubmitting; there is no durable background job
queue.

Search multipart fields are `description`, `last_seen_location`, `last_seen_at`
(ISO timestamp with timezone), optional `category`, `primary_color`, `brand`, and
`query_image`, plus required UUIDs `anonymous_session_id` and `idempotency_key`.
The browser keeps a random anonymous-session UUID in `sessionStorage`; it is
correlation only, not authentication or proof of ownership. Retrieval accepts JSON
with that UUID and the returned `search_request_id`. The date/time form is
explicitly interpreted as Manila time even when the browser uses another timezone.

## Matching and time eligibility

Qwen extracts a structured query. The database/backend enforce this hard rule
before scoring:

```text
status = available AND found_at >= last_seen_at
```

For an item recorded at 12:00, last seen at 11:59 is eligible, 12:00 is eligible,
and 12:01 is excluded. All comparisons use aware timestamps. Qwen cannot override
this rule, which concerns recorded found time rather than estimated loss time.

Deterministic names, aliases, category, brand, colors, materials, markings,
components and damage features select a shortlist. Location influences ranking,
not hard eligibility. Qwen compares one candidate at a time; image order is query,
candidate front, candidate back. Final score:

```text
100 * (0.55 * ai_similarity + 0.20 * deterministic_feature_score
       + 0.15 * location_score + 0.10 * time_proximity_score)
```

Component scores and concise explanations are audited in the database. Results
below `MATCH_MIN_SCORE` are omitted, capped at `MATCH_LIMIT`, with stable tie
ordering. The percentage is a **prototype AI match score**, not an identity
probability or proof of ownership. Ollama failure produces an error rather than
pretending AI matching succeeded.

## Simulation and privacy limits

The QR-style pass has a random opaque prototype token and ten-minute visual timer.
"Simulate station scan" shows demonstration compartment `C3`; "Simulate item
removal" calls the backend. The database locks the item row and updates status
with its event in one transaction. A repeat returns 409. Retrieved items disappear
from new searches. The UI timer is not a production authorization mechanism.

There is no physical lock/sensor control, real QR verification, production login,
missing-item posting, SMS or notification integration. Recognition remains fallible;
use representative objects to evaluate quality rather than treating self-reported
confidence or match percentages as measured accuracy.

Prompts forbid personal-data extraction from IDs/documents. Recognized sensitive
document analyses are reduced to a generic type before storage/display. This is
not certified redaction: use ordinary objects during testing. Source photographs
can still contain private details visible through authorized signed previews.
Production requires authentication, ownership checks, reviewed image redaction,
access/retention policies and secure hardware integration.

## Verification

Backend, with its environment active:

```bash
cd backend
python -m pytest -q
```

Or use this repository's existing root environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Frontend:

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

Database SQL can be tested locally without credentials using the isolated embedded
PostgreSQL harness. It is test-only and does not replace Supabase in the app:

```bash
cd supabase/tests
npm ci
npm test
```

See [supabase/README.md](supabase/README.md) for what this verifies and its limits.
External API boundary tests use test fixtures; a live Supabase acceptance run is
still required after configuring a development project.

Manual acceptance:

1. Confirm `/health` shows dependencies ready. Check desktop and mobile `/station`, mobile
   `/retrieve`, keyboard navigation and focus.
2. Try a missing image, invalid file and oversized photo; none should submit.
   Capture two ordinary item views in sequence, replace/remove previews, enter a
   location, submit once and observe the pipeline log on the identifying screen.
3. Check item code, summary and Manila found time. Verify private Storage and
   database paths, not permanent public URLs.
4. Search with matching description and last-seen time before found time. Test
   optional image and filters. Review both views, matches and contradictions.
5. Set last-seen time after found time: the item must be excluded. A different
   location may reduce its score but is not a hard exclusion.
6. Confirm, simulate scan and removal. Verify one event, retrieved status and
   exclusion from new searches. Repeat the simulation endpoint: expect 409.
7. Test expiry, cancellation, unavailable backend/Ollama and empty results. No
   successful response should be fabricated. Reopen details for fresh signed URLs.

## References

Implementation follows official [Next.js setup](https://nextjs.org/docs/app/getting-started/installation),
[FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/),
[Ollama chat](https://docs.ollama.com/api/chat), and
[Supabase key guidance](https://supabase.com/docs/guides/api/api-keys).
#   S A U L I - v 0 . 1  
 