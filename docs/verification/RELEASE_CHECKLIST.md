# Release verification

## Automated gates

- [x] Backend full pytest suite
- [x] Backend Ruff and Python compile
- [x] Frontend Vitest, ESLint, TypeScript, and production build
- [x] High-severity npm audit
- [x] Five mocked archetypes through FastAPI SSE; frontend reducers/components exercised with synthetic SSE
- [x] Next.js proxy preserves a progressively delivered upstream SSE body
- [x] Compose, JSON, and YAML validation
- [x] Backend and standalone frontend container builds; production images smoke-tested (backend readiness `503` without secrets, frontend `200`)
- [x] Credential/placeholder scan and `git diff --check`

Record exact commands and results in the ignored Task 5 report before committing.

## Visual fidelity ledger

Reference: `docs/design/skylark-signal-concept.png`.

| View | Evidence | Acceptance notes |
|---|---|---|
| Desktop | `docs/verification/screenshots/desktop.png` | Pass: calm editorial shell, persistent navigation/evidence rails, readable center column, anchored composer, and no horizontal overflow at 1440×1000. |
| Mobile | `docs/verification/screenshots/mobile.png` | Pass: single-column hierarchy, reachable composer/actions, evidence-drawer control, readable type, and no horizontal clipping on iPhone 13 emulation. |

The captures preserve the concept's dark green editorial palette, lime status/action accent, serif display headline, three-pane desktop composition, evidence-first rail, and bottom composer. The mobile composition intentionally collapses both side rails behind controls, and the empty state substitutes safe suggested prompts for the concept's populated live-data answer. Implemented turn states add live streaming stages, typed provenance/quality drawers, a copyable leadership draft, retry state, and accessible focus/announcements. Screenshots contain empty-state content only—no credentials or live board rows.

## Deployment-owner checks

1. Connect the reviewed repository to Render using `render.yaml` and supply every `sync: false` value.
2. Confirm `/health` reports ready without exposing configuration values.
3. Deploy `frontend/` to Vercel with server-only `BACKEND_URL`, then restrict backend CORS to that origin.
4. Exercise all five prompts against copied evaluation boards; compare board item counts and quality exclusions with monday.
5. Review mobile/desktop, error/partial behavior, and leadership draft-only semantics.
6. Publish verified public application and repository links by replacing README's pending labels.
