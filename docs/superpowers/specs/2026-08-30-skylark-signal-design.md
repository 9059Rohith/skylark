# Skylark Signal Design Specification

## Outcome

Build a deployable conversational BI workspace that reads live Deals and Work Orders from monday.com, normalizes messy values without hiding uncertainty, computes deterministic business metrics, and uses Claude only to interpret and explain results. Every answer exposes its board provenance and a structured data-quality report.

## Architecture

The Python 3.11 backend is a FastAPI service. A hand-built LangGraph runs `parse_intent -> plan_data_needs -> fetch_from_monday -> clean_and_normalize -> analyze -> synthesize_answer -> format_response`, with a conditional `clarify` terminal. Independent board reads run concurrently. A typed `MondayClient` boundary supports an official-hosted-MCP adapter shape and a production GraphQL transport; GraphQL is the executable fallback because this build environment has neither monday credentials nor a configured MCP session. The transport remains read-only and normalizes monday column-value variants before cleaning.

Deterministic intelligence functions own arithmetic. Claude receives compact aggregate facts, lineage, and caveats—not an instruction to invent metrics. Conversation state is keyed by caller-provided session ID through a LangGraph checkpointer. Production can use Postgres when configured; local use is in-memory.

The Next.js App Router frontend is one responsive product surface: a focused chat, an evidence rail, streaming progress, expandable caveats, and a draft leadership-update card. The accepted reference is `docs/design/skylark-signal-concept.png`. The visual system uses an ink background, elevated green-charcoal surfaces, parchment text, restrained acid-lime accents, amber caveats, editorial headings, and compact UI typography.

## Data rules

- Dates accept ISO, Indian/European slash dates, US dash dates, and named-month formats. Ambiguous slash/dash input follows the documented shape; invalid and absent values stay flagged.
- Amounts normalize to INR base units. `L`, `Cr`, and `k` multipliers are supported. Dollar amounts require `USD_TO_INR_RATE`; when absent they are invalid rather than silently treated as INR.
- Sector labels first use aliases, then RapidFuzz with a conservative threshold. Low-confidence values remain `Unclassified`.
- Missing values never remove whole records. Each metric reports total rows, included rows, exclusions by reason, and normalization notes.
- Duplicate-ish records are flagged using normalized client, amount tolerance, and close-date proximity; they are never merged.

## Product behavior

The router explicitly supports pipeline health, won-deal/work-order gaps, completion time, data-quality questions, and leadership drafts. Fiscal quarters default to calendar quarters unless `FISCAL_YEAR_START_MONTH` is configured; time phrases are resolved against a configurable timezone and clock. A truly ambiguous sector or absent fiscal context produces exactly one targeted clarification.

The `/chat` endpoint emits typed SSE events (`status`, `sources`, `caveats`, `leadership_update`, `token`, `done`, `error`). The frontend proxy never exposes credentials. `/health` reports service readiness without secrets.

## Security and operations

Secrets are environment-only. Logs redact tokens and do not include raw board records. CORS is allow-listed. Request size, history length, timeouts, pagination, retry-after/backoff, schema-cache TTL, and concurrent board fetches are bounded. No monday mutation exists in the client or tool layer.

## Verification

Backend tests cover normalization, quality accounting, routing, intelligence, monday response normalization, retry/error behavior, and API contracts. Frontend verification includes type-check, lint, production build, a mocked streaming interaction, desktop and mobile screenshots, keyboard/focus behavior, and comparison against the accepted concept.

## Delivery truthfulness

Local, Docker, Render, and Vercel artifacts must be complete. A public URL cannot be truthfully created without the user's monday/Anthropic credentials and hosting accounts; this is documented as the only external deployment blocker rather than replaced with a fake URL.
