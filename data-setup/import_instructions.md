# One-time monday.com data setup

Use the original assignment spreadsheets only as local import sources. Do **not** copy them, exports, tokens, board IDs, or row values into this repository.

## 1. Import the boards

1. In the target monday workspace, choose **Add > New board > Import data > Excel**.
2. Import **Deal Funnel Data** into a new private board named `Deals`. Select `Deal Name` as the monday item name and retain `Client Code` as a separate Text column.
3. In **Work Order Tracker**, delete/skip the blank first spreadsheet row so row 2 is treated as the header. Import it into a new private board named `Work Orders`, select `Deal name masked` as the item name, and retain `Customer Name Code` as Text.
4. Do not treat `Serial #` as a deal relation. It is the work-order identifier. Create a separate Connect Boards `Linked Deal` column only if relations are manually verified.
5. Review the inferred types and adjust them using the mapping below. Keep messy source values as Text when converting them to Date/Numbers would discard evidence.

| Workbook / semantic field | Preferred monday type | Notes |
|---|---|---|
| Deal Funnel: `Deal Name` | Item name | Shared cross-board match key |
| Deal Funnel: `Client Code` | Text | Preserve masked code; not assumed equal to work-order code |
| Deal Funnel: `Deal Status` | Status | Authoritative Open/On Hold/Dead/Won outcome |
| Deal Funnel: `Deal Stage` | Status or Text | Funnel progression; do not merge with Deal Status |
| Deal Funnel: `Masked Deal value` | Numbers when clean, otherwise Text | Runtime parses supported currency forms |
| Deal Funnel: `Sector/service` | Dropdown or Text | Preserve source taxonomy |
| Deal Funnel: `Close Date (A)` | Date when clean, otherwise Text | Actual close, preferred when present |
| Deal Funnel: `Tentative Close Date` | Date when clean, otherwise Text | Active-deal period fallback |
| Deal Funnel: last reached stage / history | Text | Optional funnel evidence |
| Work Order: `Deal name masked` | Item name | Normalized deal-name match before client fallback |
| Work Order: `Customer Name Code` | Text | Preserve source masked code |
| Work Order: `Serial #` | Text | Work-order ID, never an inferred deal ID |
| Work Order: `Execution Status` | Status | Operational-risk status |
| Work Order: `Probable Start Date` | Date/Text | Planned start |
| Work Order: `Data Delivery Date` | Date/Text | Actual completion for cycle-time metrics |
| Work Order: `Probable End Date` | Date/Text | Overdue-risk comparison |
| Work Order: `Sector` | Dropdown or Text | Optional breakdown field |

The complete expected titles and accepted aliases are in [board_schema.md](board_schema.md).

## 2. Link and verify

If independently verified relation data is available, add `Linked Deal` as a **Connect Boards** column targeting `Deals`. Do not convert `Serial #` into that relation. Matching order is exact relation ID, normalized deal name, then normalized client code. The supplied client masks differ between workbooks, so deal-name matching is the practical fallback and uncertain rows remain visible in quality accounting.

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
