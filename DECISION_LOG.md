# Decision Log

I treated this as a small production system, not a spreadsheet demo. These are the decisions that materially shaped it.

## Data and schema

I kept the supplied workbooks out of source control and made their import a one-time manual monday step. The live board schema is the contract at runtime. I resolve semantic fields from normalized column **titles** plus documented aliases instead of assuming monday's opaque column IDs equal business names. For unavoidable messy values, I preserve the source text, normalize defensively, and exclude unresolvable rows with counts and reasons.

I use exact relation IDs first when matching won deals to work orders, then normalized deal name, then normalized client code. The supplied workbooks mask client codes differently, while both contain deal names; `Serial #` is a work-order ID and is never treated as a deal relation. Work orders with no usable match key remain part of total quality accounting but cannot count as matching evidence. Duplicate IDs, ambiguous currencies, invalid dates, and missing required fields are surfaced rather than silently coerced.

I keep `Deal Status` (Open/On Hold/Dead/Won) separate from the lettered `Deal Stage` funnel. Status is authoritative for won-gap analysis; stage aliases support progression reporting. I interpret “quarter” as a calendar quarter unless `FISCAL_YEAR_START_MONTH` changes that policy. Deal scope prefers `Close Date (A)` and falls back to `Tentative Close Date`, completion metrics use `Data Delivery Date`, and cross-board scope retains all usable work-order evidence. A quality question scoped to a period asks permission to use the full board because rows missing dates cannot honestly be assigned to that period.

Sector is a canonicalized label, not a guessed hierarchy. I preserve workbook labels for breakdowns, while the evaluator's `Energy` query group explicitly includes Energy, Renewables, and Powerline. Ambiguous multi-select values remain Unclassified, and an ambiguous or absent requested sector triggers one focused clarification.

## Agent and provider choices

I chose a hand-rolled LangGraph `StateGraph` so routing, the clarification loop, board needs, and node order remain inspectable and testable. Deterministic code owns routing when possible, filtering, arithmetic, quality reports, direct-answer prefixes, and material-caveat suffixes. The model receives only compact aggregate facts and may contribute bounded qualitative context. Session IDs are UUIDv4; in-memory checkpoints are TTL/count bounded, active sessions are pinned, and raw prompts are execution context rather than checkpoint state. This is deliberately a single-worker default; a shared production checkpointer is the scaling seam.

The requested hosted monday MCP endpoint was not available in the build environment. I therefore defined an MCP-compatible monday tool interface and supplied an executable, query-only GraphQL adapter using API version `2026-07`. This preserves a clean replacement boundary without pretending an unavailable integration was used.

The initial design named Claude, but the user had no Anthropic credential and explicitly authorized an OpenAI key. I made the official OpenAI Responses API and `gpt-5.4-mini` the production default, including real output-delta streaming. Anthropic remains an environment-selected adapter, so provider choice is one setting. This is an intentional, documented deviation—not a claim that Claude was exercised.

## Product and operations

I interpret “leadership update” strictly as a typed, reviewable draft. It contains a headline, sector breakdown, risks, per-section quality, footnote, and Markdown. There is no send, monday mutation, email, Slack, or write action. Copying and publication stay in a human approval loop.

I expose sources and complete quality reports alongside answers because a polished number without its denominator is unsafe. A later-page monday failure may yield a labeled partial result when usable rows exist; failure of any board required for a cross-board answer yields a clean unavailable error with the successful provenance preserved. Provider and upstream exceptions are sanitized before reaching SSE.

I selected FastAPI/Python 3.11 for typed async data work, Next.js App Router/TypeScript/Tailwind for the streaming evidence UI, Render Docker for the backend, and Vercel for the frontend. `BACKEND_URL` remains server-only. Secrets are injected by hosting platforms and health reports readiness without secret values.

With more time I would add application authentication and audit identity, Postgres-backed checkpoints for multi-worker operation, an OAuth monday app with per-user authorization, observability/redaction audits, richer schema-drift alerts, confidence-assisted entity resolution, browser end-to-end tests against an ephemeral backend, and an owner-run staging deployment using copied non-sensitive boards. Public URLs remain pending because only the deployment owner can provide hosting access and production credentials.
