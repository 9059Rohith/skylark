"""Deterministic deals/work-order correlation metrics."""

from collections import Counter
from collections.abc import Sequence

from app.cleaning.quality_report import DataQualityReport
from app.intelligence.records import Record, normalized_key, record_value, text_value
from app.intelligence.schemas import AnalysisResult


def _relation_ids(value: object) -> set[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {
            normalized
            for item in value
            if (normalized := text_value(item)) is not None
        }
    normalized = text_value(value)
    return {normalized} if normalized is not None else set()


def won_deals_without_work_orders(
    deals: Sequence[Record], work_orders: Sequence[Record]
) -> AnalysisResult:
    """Find won deals lacking an exact relation-ID or normalized-client match."""
    usable_work_orders = []
    work_order_exclusions: Counter[str] = Counter()
    for work_order in work_orders:
        relation_ids = _relation_ids(
            record_value(work_order, "deal_id", "linked_deal_id")
        )
        client = text_value(
            record_value(work_order, "client", "client_name", "customer")
        )
        if not relation_ids and client is None:
            work_order_exclusions["work_order:missing_match_key"] += 1
            continue
        usable_work_orders.append(work_order)
    work_order_deal_ids = set().union(
        *(
            _relation_ids(record_value(work_order, "deal_id", "linked_deal_id"))
            for work_order in usable_work_orders
        )
    )
    work_order_clients = {
        normalized_key(value)
        for work_order in usable_work_orders
        if (value := text_value(record_value(work_order, "client", "client_name", "customer")))
    }

    won_count = 0
    matchable_count = 0
    matched = 0
    missing: list[dict[str, str | None]] = []
    exclusions: Counter[str] = Counter()
    exclusions.update(work_order_exclusions)
    for deal in deals:
        stage = text_value(record_value(deal, "stage", "status", "deal_stage"))
        if stage is None or stage.casefold() != "won":
            exclusions["not_won"] += 1
            continue
        won_count += 1
        deal_id = text_value(record_value(deal, "id", "item_id", "deal_id"))
        client = text_value(record_value(deal, "client", "client_name", "customer"))
        if deal_id is None and client is None:
            exclusions["missing_match_key"] += 1
            continue
        matchable_count += 1
        relation_match = deal_id is not None and deal_id in work_order_deal_ids
        client_match = client is not None and normalized_key(client) in work_order_clients
        if relation_match or client_match:
            matched += 1
        else:
            missing.append(
                {
                    "deal_id": deal_id,
                    "deal_name": text_value(record_value(deal, "name")),
                    "client": client,
                }
            )
    return AnalysisResult(
        metrics={
            "won_deal_count": won_count,
            "matched_work_order_count": matched,
            "missing_work_order_count": len(missing),
            "missing_work_orders": missing,
        },
        quality=DataQualityReport(
            total_rows=len(deals) + len(work_orders),
            included_rows=matchable_count + len(usable_work_orders),
            exclusions=dict(exclusions),
            normalization_notes=[
                "Work orders match won deals by exact relation ID, then normalized client name.",
                "Quality accounting includes target deal rows and work orders with a usable relation or client match key.",
            ],
        ),
    )
