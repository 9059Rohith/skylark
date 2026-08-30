# Live board schema contract

The adapter loads monday's live column metadata and normalizes titles by case and whitespace. Source column IDs are opaque and are never assumed to equal these names.

## Deals board

| Semantic field | Canonical title | Accepted normalized aliases | Used by |
|---|---|---|---|
| Client | `Client` | `client name`, `customer`, `customer name`, `account` | display, fallback matching |
| Stage | `Stage` | `deal stage`, `pipeline stage`, `status` | pipeline, won-gap analysis |
| Amount | `Amount` | `deal value`, `contract value`, `pipeline value`, `estimated value` | pipeline value |
| Sector | `Sector` | `industry`, `vertical`, `industry vertical` | breakdown/follow-up |
| Close date | `Close Date` | `expected close`, `expected close date`, `closed date` | deal period scope |
| Last reached stage | `Last Reached Stage` | `last stage before loss` | stage context |
| Stage history | `Stage History` | `stage history values` | stage context |

Minimum useful fields vary by question. Missing required values are exclusions, not zeroes. Amounts accept Indian/Western separators and common currency symbols/codes; ambiguous or unconfigured conversions are excluded.

## Work Orders board

| Semantic field | Canonical title | Accepted normalized aliases | Used by |
|---|---|---|---|
| Related deal | `Deal ID` | `linked deal`, `linked deal id`, `deal relation` | exact cross-board matching |
| Client | `Client` | `client name`, `customer`, `customer name` | fallback matching/display |
| Start date | `Start Date` | `started date`, `kickoff`, `kickoff date`, `created date` | completion duration |
| Completion date | `Completion Date` | `completed date`, `completed`, `end date` | completion period/duration |
| Status | `Status` | `work order status` | operational risk |
| Sector | `Sector` | `industry`, `vertical`, `industry vertical` | optional breakdown |

A work order is usable cross-board evidence only when it has a relation ID or normalized client match key. Otherwise it is reported as `work_order:missing_match_key`. A completion duration also requires valid start/completion dates and a non-negative interval.

## Verification rules

- Preserve raw source values in monday; normalization happens in the read-only application.
- Prefer one semantic field per board. If multiple aliases coexist, consolidate them before evaluation to avoid ambiguous mappings.
- Confirm the token can read both board metadata and items, including connected-board values.
- Validate representative blank, duplicate, currency, date, and status rows after import.
- Treat new/renamed titles as schema drift: update this document, the alias mapping, and contract tests together.
