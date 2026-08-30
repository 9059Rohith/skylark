# Live board schema contract

The adapter loads monday's live column metadata and normalizes titles by case and whitespace. Source column IDs are opaque and are never assumed to equal these names.

## Deals board

| Semantic field | Canonical title | Accepted normalized aliases | Used by |
|---|---|---|---|
| Deal name | `Deal Name` | monday item name fallback | display and cross-board matching |
| Client | `Client Code` | `client`, `client name`, `customer`, `customer name`, `account` | final fallback matching |
| Outcome | `Deal Status` | — | authoritative Open/On Hold/Dead/Won result |
| Funnel stage | `Deal Stage` | `stage`, `pipeline stage` | progression only; never conflated with outcome |
| Amount | `Masked Deal value` | `amount`, `deal value`, `contract value`, `pipeline value`, `estimated value` | pipeline value |
| Sector | `Sector/service` | `sector`, `industry`, `vertical`, `industry vertical` | breakdown/follow-up |
| Actual close | `Close Date (A)` | `close date`, `actual close date`, `closed date` | preferred deal scope date |
| Tentative close | `Tentative Close Date` | `expected close`, `expected close date` | scope fallback for active deals |
| Last reached stage | `Last Reached Stage` | `last stage before loss` | stage context |
| Stage history | `Stage History` | `stage history values` | stage context |

Minimum useful fields vary by question. Missing required values are exclusions, not zeroes. Amounts accept Indian/Western separators and common currency symbols/codes; ambiguous or unconfigured conversions are excluded.

## Work Orders board

| Semantic field | Canonical title | Accepted normalized aliases | Used by |
|---|---|---|---|
| Related deal | `Linked Deal` | `deal id`, `linked deal id`, `deal relation` | optional explicit Connect Boards relation |
| Deal name | `Deal name masked` | monday item name fallback | normalized cross-board matching |
| Client | `Customer Name Code` | `client`, `client name`, `customer`, `customer name` | final fallback matching |
| Work-order ID | `Serial #` | `serial`, `serial number` | identity only; not a deal relation |
| Start date | `Probable Start Date` | `start date`, `started date`, `kickoff`, `kickoff date` | planned start |
| Completion date | `Data Delivery Date` | `completion date`, `completed date`, `completed`, `end date` | completion period/duration |
| Expected end | `Probable End Date` | `expected end date` | overdue risk |
| Status | `Execution Status` | `status`, `work order status` | operational risk |
| Sector | `Sector` | `industry`, `vertical`, `industry vertical` | optional breakdown |

A work order is usable cross-board evidence only when it has a relation ID or normalized client match key. Otherwise it is reported as `work_order:missing_match_key`. A completion duration also requires valid start/completion dates and a non-negative interval.

## Verification rules

- Preserve raw source values in monday; normalization happens in the read-only application.
- Use Deal Name / Deal name masked as item names. Item-name-as-client is disabled unless a different board is explicitly configured for that semantic.
- `Energy` query scope expands to the preserved `Energy`, `Renewables`, and `Powerline` labels; breakdowns keep the original canonical labels.
- Prefer one semantic field per board. If multiple aliases coexist, consolidate them before evaluation to avoid ambiguous mappings.
- Confirm the token can read both board metadata and items, including connected-board values.
- Validate representative blank, duplicate, currency, date, and status rows after import.
- Treat new/renamed titles as schema drift: update this document, the alias mapping, and contract tests together.
