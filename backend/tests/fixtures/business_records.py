"""Synthetic business records for deterministic intelligence tests."""

DEALS = [
    {
        "id": "d-1",
        "name": "Acme expansion",
        "client": "Acme, Inc.",
        "stage": "Won",
        "amount": "INR 10,00,000",
        "sector": "IT Services",
        "close_date": "2026-08-10",
    },
    {
        "id": "d-2",
        "name": "Acme expansion copy",
        "client": " acme inc ",
        "stage": "Proposal",
        "amount": "INR 10,20,000",
        "sector": "technlogy",
        "close_date": "2026-08-17",
    },
    {
        "id": "d-3",
        "name": "Beta rollout",
        "client": "Beta Ltd",
        "stage": "Won",
        "amount": "2 Cr",
        "sector": "energy sector",
        "close_date": "",
    },
    {
        "id": "d-4",
        "name": "Unknown value",
        "client": "Gamma",
        "stage": "Qualified",
        "amount": "many rupees",
        "sector": "garden supplies",
        "close_date": "not a date",
    },
]

WORK_ORDERS = [
    {
        "id": "wo-1",
        "name": "Acme delivery",
        "deal_id": "d-1",
        "client": "Acme Inc",
        "start_date": "2026-08-11",
        "completion_date": "2026-08-21",
    },
    {
        "id": "wo-2",
        "name": "Bad chronology",
        "deal_id": "d-x",
        "client": "Other",
        "start_date": "2026-08-20",
        "completion_date": "2026-08-19",
    },
    {
        "id": "wo-3",
        "name": "Incomplete",
        "deal_id": "d-y",
        "client": "Another",
        "start_date": "2026-08-20",
        "completion_date": "",
    },
]
