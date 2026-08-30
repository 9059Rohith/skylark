"""Deterministic deals/work-order correlation metrics."""

from collections import Counter
from collections.abc import Sequence

from app.cleaning.quality_report import DataQualityReport
from app.intelligence.deal_lifecycle import classify_deal_lifecycle
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
    """Match won deals through exclusive relation, name, then client phases."""
    relation_work_orders: list[tuple[Record, set[str]]] = []
    name_work_orders: list[tuple[Record, str]] = []
    client_work_orders: list[tuple[Record, str]] = []
    work_order_exclusions: Counter[str] = Counter()
    for work_order in work_orders:
        relation_ids = _relation_ids(
            record_value(work_order, "deal_id", "linked_deal_id")
        )
        client = text_value(
            record_value(work_order, "client", "client_name", "customer")
        )
        deal_name = text_value(record_value(work_order, "deal_name", "name"))
        if relation_ids:
            relation_work_orders.append((work_order, relation_ids))
        elif deal_name is not None:
            name_work_orders.append((work_order, normalized_key(deal_name)))
        elif client is not None:
            client_work_orders.append((work_order, normalized_key(client)))
        else:
            work_order_exclusions["work_order:missing_match_key"] += 1
    explicitly_linked_ids = set().union(
        *(relation_ids for _, relation_ids in relation_work_orders)
    )

    won_count = 0
    matchable_count = 0
    target_deals: list[dict[str, str | None]] = []
    exclusions: Counter[str] = Counter()
    exclusions.update(work_order_exclusions)
    for deal in deals:
        if classify_deal_lifecycle(deal) != "closed_won":
            exclusions["not_won"] += 1
            continue
        won_count += 1
        deal_id = text_value(record_value(deal, "id", "item_id", "deal_id"))
        client = text_value(record_value(deal, "client", "client_name", "customer"))
        deal_name = text_value(record_value(deal, "deal_name", "name"))
        if deal_id is None and deal_name is None and client is None:
            exclusions["missing_match_key"] += 1
            continue
        matchable_count += 1
        target_deals.append(
            {"deal_id": deal_id, "deal_name": deal_name, "client": client}
        )

    matched_indexes = {
        index
        for index, deal in enumerate(target_deals)
        if deal["deal_id"] is not None and deal["deal_id"] in explicitly_linked_ids
    }
    used_name_work_orders: set[int] = set()
    for deal_index, deal in enumerate(target_deals):
        if deal_index in matched_indexes or deal["deal_name"] is None:
            continue
        key = normalized_key(deal["deal_name"])
        match_index = next(
            (
                index
                for index, (_, candidate_key) in enumerate(name_work_orders)
                if index not in used_name_work_orders and candidate_key == key
            ),
            None,
        )
        if match_index is not None:
            used_name_work_orders.add(match_index)
            matched_indexes.add(deal_index)

    used_client_work_orders: set[int] = set()
    for deal_index, deal in enumerate(target_deals):
        if deal_index in matched_indexes or deal["client"] is None:
            continue
        key = normalized_key(deal["client"])
        match_index = next(
            (
                index
                for index, (_, candidate_key) in enumerate(client_work_orders)
                if index not in used_client_work_orders and candidate_key == key
            ),
            None,
        )
        if match_index is not None:
            used_client_work_orders.add(match_index)
            matched_indexes.add(deal_index)

    missing = [
        deal for index, deal in enumerate(target_deals) if index not in matched_indexes
    ]
    matched = len(matched_indexes)
    usable_work_order_count = (
        len(relation_work_orders) + len(name_work_orders) + len(client_work_orders)
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
            included_rows=matchable_count + usable_work_order_count,
            exclusions=dict(exclusions),
            normalization_notes=[
                "Work orders match won deals by exclusive exact relation ID, normalized deal name, then normalized client name phases.",
                "Unlinked name/client fallback work orders are consumed at most once in deterministic source order; source rows are never merged.",
                "Quality accounting includes target deal rows and work orders with a usable relation, deal-name, or client match key.",
                *(
                    ["Client matching used the monday item name where the Client column was blank or absent."]
                    if any(
                        record_value(row, "_client_source") == "item_name_fallback"
                        for row in [*deals, *work_orders]
                    )
                    else []
                ),
                *(
                    ["Deal-name matching used the monday item name where the mapped Deal Name column was blank or absent."]
                    if any(
                        record_value(row, "_deal_name_source") == "item_name_fallback"
                        for row in [*deals, *work_orders]
                    )
                    else []
                ),
            ],
        ),
    )
