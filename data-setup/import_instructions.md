# One-time monday.com data setup

Use the original assignment spreadsheets only as local import sources. Do **not** copy them, exports, tokens, board IDs, or row values into this repository.

## 1. Import the boards

1. In the target monday workspace, choose **Add > New board > Import data > Excel**.
2. Import **Deal Funnel Data** into a new private board named `Deals`.
3. Import **Work Order Tracker** into a new private board named `Work Orders`.
4. Select the business-name/client column as each item's name when the wizard asks.
5. Review the inferred types and adjust them using the mapping below. Keep messy source values as Text when converting them to Date/Numbers would discard evidence.

| Workbook / semantic field | Preferred monday type | Notes |
|---|---|---|
| Deal Funnel: client | Name or Text | Required matching/display field |
| Deal Funnel: stage | Status | Preserve source label; won/lost aliases normalize at runtime |
| Deal Funnel: amount/value | Numbers when clean, otherwise Text | Include currency code/symbol when values are mixed |
| Deal Funnel: sector | Dropdown or Text | Keep the source taxonomy |
| Deal Funnel: close date | Date when clean, otherwise Text | Missing/invalid values are reported |
| Deal Funnel: last reached stage / history | Text | Optional funnel evidence |
| Work Order: linked deal | Connect Boards or Text deal ID | Relation ID is the preferred match key |
| Work Order: client | Name or Text | Normalized fallback match key |
| Work Order: start/completion dates | Date when clean, otherwise Text | Invalid dates remain quality exclusions |
| Work Order: status | Status | Used for operational-risk summaries |
| Work Order: sector | Dropdown or Text | Optional breakdown field |

The complete expected titles and accepted aliases are in [board_schema.md](board_schema.md).

## 2. Link and verify

If the workbook contains reliable deal identifiers, configure `linked deal` as a **Connect Boards** column targeting `Deals`. Retain any source deal ID as a Text column for verification. Do not invent links based only on similar names; the application can use a normalized client fallback and will report rows that have neither match key.

Open several imported items and compare dates, currency symbols/codes, status labels, blank cells, and identifiers with the source workbook. Confirm row totals in monday before continuing.

## 3. Create least-privilege access

Create a monday personal token for an evaluation-only account that can **view only these two boards**, or install a monday app granted `boards:read`. Personal tokens mirror the user's monday UI permissions, so remove unrelated board access from that account. The application issues GraphQL queries only; never grant or add mutation behavior for this prototype.

Copy `backend/.env.example` to `backend/.env` and set:

```dotenv
MONDAY_API_TOKEN=<read-only token>
MONDAY_DEALS_BOARD_ID=<Deals board numeric ID>
MONDAY_WORK_ORDERS_BOARD_ID=<Work Orders board numeric ID>
OPENAI_API_KEY=<server-side OpenAI key>
```

Board IDs are visible in each board URL. Keep this file local—it is gitignored—and use Render/Vercel secret stores in production.

## 4. Runtime schema check

Start the backend and request `GET /health`. A configured service reports `ready`. Then ask one prompt against each board and confirm the Sources drawer shows the expected board name and plausible item count. The adapter fetches live column IDs and titles, maps titles through the aliases, and caches schemas for 15 minutes. After renaming a column, restart the backend (or wait for cache expiry) and re-run the check.

If a required field is not recognized, prefer renaming it to a canonical title in [board_schema.md](board_schema.md). If the business title cannot change, add and test a documented alias in the backend—never hardcode the current opaque monday column ID as a semantic name.
