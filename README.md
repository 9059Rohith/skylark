# Skylark Signal

Skylark Signal is a hosted-ready conversational BI workspace for live, read-only monday.com Deals and Work Orders data. It answers five evaluator archetypes with deterministic arithmetic, explicit source counts, and visible data-quality exclusions; the language model only writes bounded qualitative context.

**Live application:** **[PENDING DEPLOYMENT — owner must connect Render, Vercel, and production secrets]**

**Source repository:** **[PENDING PUBLICATION — owner must publish the reviewed repository]**

## Architecture

```text
Browser
  |
  v
Next.js App Router (TypeScript + Tailwind)
  |  server-only /api/chat proxy; BACKEND_URL is never shipped to the browser
  v
FastAPI /chat (typed SSE: status, sources, caveats, leadership_update, token, done/error)
  |
  v
LangGraph StateGraph
parse_intent -> plan_data_needs -> fetch_from_monday -> clean_and_normalize
               ^ clarify loop                         |
               +--------------------------------------+-> analyze -> synthesize_answer -> format_response
  |                                      |
  | query-only monday tool interface     +-> OpenAI Responses API (default)
  v                                          Anthropic adapter (optional)
monday GraphQL API 2026-07
```

The backend is Python 3.11, FastAPI, Pydantic v2, and a hand-rolled LangGraph. The monday boundary is an MCP-compatible tool interface; because no hosted monday MCP endpoint was available for this build, the executable adapter calls monday GraphQL directly. Required boards are fetched concurrently, cursors are followed within a defensive page bound, and live column IDs are mapped from normalized titles and documented aliases. OpenAI `gpt-5.4-mini` is the production default; changing `LLM_PROVIDER` swaps to the optional Anthropic adapter. The frontend is Next.js App Router, TypeScript, and Tailwind. Render runs the backend Docker image and Vercel hosts the frontend.

## Quick start

Requirements: Python 3.11, Node.js 20+, and Docker Desktop for the container path.

1. Import the two supplied spreadsheets into monday by following [data-setup/import_instructions.md](data-setup/import_instructions.md). Do not add spreadsheet contents to this repository.
2. Copy `backend/.env.example` to `backend/.env`, then add the two board IDs, a read-only monday token, and an OpenAI API key.
3. Copy `frontend/.env.example` to `frontend/.env.local` for non-Docker frontend development.
4. Start the complete stack:

   ```bash
   docker compose up --build
   ```

5. Open `http://localhost:3000`; backend health is `http://localhost:8000/health`.

For direct development:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --reload --port 8000

cd frontend
npm ci
npm run dev
```

## Configuration

| Variable | Required | Default / purpose |
|---|---:|---|
| `MONDAY_API_TOKEN` | production | Read-only personal/app token; never expose to the browser |
| `MONDAY_DEALS_BOARD_ID` | production | Imported Deal Funnel Data board ID |
| `MONDAY_WORK_ORDERS_BOARD_ID` | production | Imported Work Order Tracker board ID |
| `LLM_PROVIDER` | no | `openai`; set `anthropic` to use the optional adapter |
| `OPENAI_API_KEY` | for OpenAI | OpenAI server credential |
| `OPENAI_MODEL` | no | `gpt-5.4-mini` |
| `OPENAI_TIMEOUT_SECONDS` / `OPENAI_MAX_RETRIES` / `OPENAI_MAX_TOKENS` | no | `20` / `2` / `700` |
| `ANTHROPIC_API_KEY` | for Anthropic | Optional provider credential |
| `ANTHROPIC_MODEL` | no | `claude-sonnet-5` |
| `ANTHROPIC_TIMEOUT_SECONDS` / `ANTHROPIC_MAX_RETRIES` / `ANTHROPIC_MAX_TOKENS` | no | `20` / `2` / `700` |
| `LLM_CONTEXT_MAX_CHARS` | no | `1200`; bounds qualitative model context |
| `DETERMINISTIC_SYNTHESIS_FALLBACK` | no | `false`; explicit local/test-only fallback |
| `USD_TO_INR_RATE` | when USD values occur | Decimal conversion rate; unresolved currency is excluded |
| `FISCAL_YEAR_START_MONTH` | no | `1`; valid `1`–`12` |
| `APP_TIMEZONE` | no | `Asia/Kolkata` |
| `CORS_ALLOW_ORIGINS` | no | `http://localhost:3000`; comma-separated allow-list |
| `MAX_MESSAGE_LENGTH` | no | `4000` |
| `CHECKPOINT_MAX_SESSIONS` / `CHECKPOINT_SESSION_TTL_SECONDS` | no | `1000` / `3600`; bounded in-memory sessions |
| `BACKEND_URL` | frontend | Server-only backend origin, default `http://localhost:8000` |
| `PORT` | hosting | Container HTTP port; backend defaults to `8000`, frontend `3000` |

`/health` is a readiness probe: it returns HTTP 200 only when both monday board IDs, the token, and selected provider key are configured; degraded readiness returns HTTP 503 with the same sanitized missing-setting payload.

## What to ask

- “How healthy is our pipeline this quarter?”
- “Which won deals have no work orders?”
- “What is average work order completion time this month?”
- “How many deals are missing close dates?”
- “Draft the weekly leadership update.”

Follow-ups such as “Break that down by sector” reuse the UUIDv4 session context. The leadership result is a typed, copyable **draft** with pipeline headline, sector breakdown, risks, and per-section quality; it never sends or writes anything.

## Data, provenance, and safety

Metrics and currency/date arithmetic are deterministic. `Deal Status` is distinct from the lettered funnel `Deal Stage`; status is authoritative for Won/Dead. Deal period scope prefers `Close Date (A)` and falls back to `Tentative Close Date`, while work-order completion uses `Data Delivery Date`. Cross-board matching tries an explicit relation, normalized deal name, then client code, retaining all usable work-order evidence. The `Energy` query group includes Energy, Renewables, and Powerline while breakdown labels remain distinct. A period-scoped quality request asks before broadening to the full Deals board because missing dates cannot be assigned to a period. Every response names queried boards and item counts; partial later pages are labeled, while a failed required board produces an unavailable error rather than false zeroes.

Only GraphQL queries are implemented—no monday mutations, send actions, or write tools. Keep credentials in host secret stores or ignored `.env` files, grant the minimum monday board visibility, rotate leaked tokens, restrict CORS, and review [SECURITY.md](SECURITY.md). Raw prompts and board rows are not logged or checkpointed. Process-local checkpoints are bounded but require sticky single-worker routing; substitute a production shared checkpointer before horizontal scaling.

## API and operational behavior

The monday client sends `API-Version: 2026-07`, requests up to 500 items per page, follows distinct cursors for at most 100 pages, labels repeated-cursor/page-bound truncation as partial, and retries transient rate/server errors up to three total attempts using `Retry-After` or capped exponential delay. `POST /chat` returns typed `text/event-stream`; requests require a UUIDv4 session ID and a bounded message. The frontend proxy preserves streaming and applies a 120-second timeout.

Troubleshooting:

- **Health is degraded:** confirm board IDs/token and the selected provider key in `backend/.env` or the Render secret store.
- **Board/schema error:** verify board IDs, token visibility, and column titles against [data-setup/board_schema.md](data-setup/board_schema.md); restart once after title changes to refresh the schema cache.
- **Clarification repeats:** answer the exact sector/scope choice; start a new conversation to discard prior scope.
- **Partial result:** monday returned usable earlier pages but a later page failed. Retry; do not treat the item count as complete.
- **Browser cannot connect:** set frontend `BACKEND_URL` to the reachable backend origin and add the frontend origin to `CORS_ALLOW_ORIGINS`.

## Test and release commands

```bash
python -m pytest backend/tests -q
python -m ruff check backend
python -m compileall -q backend/app backend/tests

cd frontend
npm ci
npm test
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=high
```

Run `docker compose config` and `docker compose build` before release. The machine-readable coverage map and manual verification notes are in [docs/verification/requirements.json](docs/verification/requirements.json) and [docs/verification/RELEASE_CHECKLIST.md](docs/verification/RELEASE_CHECKLIST.md).

## Deploy for evaluation

1. Push the reviewed repository to GitHub.
2. In Render, create a Blueprint from `render.yaml`; enter all `sync: false` secrets and wait for `/health` to become ready.
3. In Vercel, import `frontend/`, set server-only `BACKEND_URL` to the verified Render service origin, and deploy.
4. Update Render `CORS_ALLOW_ORIGINS` to the exact Vercel origin, redeploy, then exercise all five prompts and mobile/desktop layouts.
5. Replace the two pending labels at the top only after independently opening both public links.

## AI-tool disclosure and limitations

OpenAI Codex/GPT-5-family coding assistance was used to implement, test, and review the repository; image generation was used for a visual concept reference. No Claude API was used during the build. A human supplied the requirements, approved OpenAI as the default because no Anthropic key was available, and remains responsible for credential scope, deployment, live-data validation, and publication.

Known limitations: no public deployment can be completed without the owner's hosting accounts and secrets; monday imports are one-time manual setup; dirty repeated-header rows remain visible as quality exclusions; live schema/type changes may require cache refresh; in-memory sessions are single-process; normalized deal-name/client fallback can be ambiguous; currency conversion needs an explicit rate; no authentication layer is bundled for the prototype; and leadership updates are draft-only.

See [DECISION_LOG.md](DECISION_LOG.md) for the concise implementation rationale.
