# Skylark Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production-ready monday.com conversational BI application with traceable deterministic metrics, provider-swappable LLM synthesis, streaming chat, and deployment documentation.

**Architecture:** FastAPI and a typed monday transport feed a hand-built LangGraph whose nodes separate intent, retrieval, normalization, analysis, and synthesis. A Next.js App Router client consumes typed SSE and renders a responsive evidence-first chat workspace.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, LangGraph, OpenAI Responses API by default with an optional Anthropic adapter, HTTPX, RapidFuzz, pytest; Next.js, React, TypeScript, Tailwind, Vitest; Docker, Render, Vercel. The user authorized the OpenAI default (`gpt-5.4-mini`) because no Anthropic key was available.

**Spec:** `docs/superpowers/specs/2026-08-30-skylark-signal-design.md`

## Global Constraints

- monday.com access is read-only and live; application code contains no sample CSV records.
- All business metrics return `DataQualityReport` alongside results.
- Secrets stay server-side and are configured only through environment variables.
- The five required query archetypes must have explicit routing and test coverage.
- Leadership updates are human-reviewed drafts and never sent externally.

---

### Task 1: Repository and cleaning foundation

**Files:** Create the requested repository tree, Python project configuration, `backend/app/cleaning/*`, typed schemas, and `backend/tests/test_normalizer.py`.

**Interfaces:** `normalize_date(value) -> NormalizedValue[date]`, `normalize_currency(value, usd_to_inr_rate) -> NormalizedValue[Decimal]`, `normalize_sector(value) -> NormalizedValue[str]`, `DataQualityReport.merge(...)`.

- [ ] Write focused tests for every required date, amount, sector, missing-value, and duplicate case.
- [ ] Run the tests and confirm failures are caused by missing behavior.
- [ ] Implement the smallest typed normalization and quality-report layer.
- [ ] Run the focused suite, then refactor while green.

### Task 2: monday transport and intelligence

**Files:** Create `backend/app/monday/*`, `backend/app/intelligence/*`, synthetic fixtures, and transport/metric tests.

**Interfaces:** async `get_board_schema`, `get_board_items`, and `search_items`; metric functions return `AnalysisResult` with `metrics` and `quality`.

- [ ] Write failing tests for monday column normalization, pagination, search behavior, failure classification, pipeline, operations, and cross-board matching.
- [ ] Verify the new tests fail for the intended missing interfaces.
- [ ] Implement cursor pagination, TTL schema caching, bounded retry, partial-result caveats, and deterministic intelligence.
- [ ] Run and refactor the full backend test set.

### Task 3: Agent and API

**Files:** Create `backend/app/agent/*`, `backend/app/leadership/*`, `backend/app/main.py`, configuration, API/routing tests, Docker assets.

**Interfaces:** `build_graph(dependencies)`, `run_agent(message, session_id)`, typed SSE event models, `GET /health`, `POST /chat`.

- [ ] Write failing routing, graph-node, leadership-output, and streaming API tests.
- [ ] Verify red state.
- [ ] Implement explicit routes, concurrent fetch, checkpointed state, provider-swappable structured parsing/synthesis with deterministic fallback, and SSE formatting.
- [ ] Run all backend tests and static checks.

### Task 4: Frontend product surface

**Files:** Create `frontend/app/*`, `frontend/components/*`, streaming client utilities, UI tests, and deployment settings.

**Interfaces:** `POST /api/chat` proxies SSE; `ChatWindow` reduces typed events into message, sources, caveats, progress, and leadership state.

- [ ] Write failing reducer/component tests for stream events, copy-as-Markdown, caveat disclosure, error recovery, and session continuity.
- [ ] Verify red state.
- [ ] Implement the accepted concept with accessible semantic controls and responsive desktop/mobile layouts.
- [ ] Run tests, lint, type-check, and production build.

### Task 5: Documentation, deployment, and release audit

**Files:** Create `README.md`, `DECISION_LOG.md`, `data-setup/*`, `docker-compose.yml`, `render.yaml`, security policy, and verification notes.

- [ ] Document exact board import mappings, environment variables, architecture, local/deployment steps, limitations, and AI-tool disclosure.
- [ ] Run Docker/config validation and secret/placeholder scans.
- [ ] Exercise all five archetypes with mocked live-client responses through the API and UI.
- [ ] Capture desktop/mobile screenshots, compare to the concept, record and repair the fidelity ledger.
- [ ] Re-read every assignment line, map it to evidence, and report only externally blocked deployment steps.
