"""Deterministic deals-pipeline metrics with explicit quality accounting."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP

from app.cleaning.normalizer import (
    normalize_currency,
    normalize_date,
    normalize_sector,
    normalize_stage,
)
from app.cleaning.quality_report import DataQualityReport
from app.cleaning.rules import DuplicateCandidate, find_duplicate_candidates
from app.intelligence.deal_lifecycle import classify_deal_lifecycle
from app.intelligence.records import Record, record_value, text_value
from app.intelligence.schemas import AnalysisResult


DEFAULT_STAGE_ORDER = ("Lead", "Qualified", "Proposal", "Negotiation", "Won")
_TWO_PLACES = Decimal("0.01")


def _deal_id(deal: Record) -> str:
    return text_value(record_value(deal, "id", "item_id", "deal_id")) or ""


def _amount(deal: Record, usd_to_inr_rate: Decimal | None):
    return normalize_currency(
        record_value(deal, "amount", "deal_value", "pipeline_value", "estimated_value"),
        usd_to_inr_rate,
    )


def _duplicate_pairs(
    deals: Sequence[Record], usd_to_inr_rate: Decimal | None
) -> list[tuple[str, str]]:
    candidates: list[DuplicateCandidate] = []
    for deal in deals:
        amount = _amount(deal, usd_to_inr_rate)
        close_date = normalize_date(
            record_value(deal, "close_date", "expected_close_date", "closed_date")
        )
        candidates.append(
            DuplicateCandidate(
                record_id=_deal_id(deal),
                client_name=text_value(
                    record_value(deal, "client", "client_name", "account", "customer")
                ),
                amount=amount.value if amount.is_valid else None,
                close_date=close_date.value if close_date.is_valid else None,
            )
        )
    return [
        (flag.record_id, flag.matching_record_id)
        for flag in find_duplicate_candidates(candidates)
    ]


def pipeline_health(
    deals: Sequence[Record], *, usd_to_inr_rate: Decimal | None = None
) -> AnalysisResult:
    """Calculate active pipeline without removing duplicate-ish active source rows."""
    total = Decimal("0")
    valid_amounts = 0
    active_deals: list[Record] = []
    exclusions: Counter[str] = Counter()
    for deal in deals:
        status = classify_deal_lifecycle(deal)
        if status != "active":
            exclusions[f"pipeline_status:{status}"] += 1
            continue
        active_deals.append(deal)
        amount = _amount(deal, usd_to_inr_rate)
        if amount.is_valid and amount.value is not None:
            total += amount.value
            valid_amounts += 1
        else:
            exclusions[amount.reason or "invalid_currency"] += 1
    average = total / valid_amounts if valid_amounts else None
    duplicates = _duplicate_pairs(active_deals, usd_to_inr_rate)
    notes = [
        "Active pipeline includes Open, On Hold, Lead, Qualified, Proposal, and Negotiation stages only.",
        "Won, Lost, Dead, and unknown-stage rows are excluded from the headline and reported explicitly.",
        "Amounts are normalized to INR base units.",
    ]
    if any(record_value(deal, "_client_source") == "item_name_fallback" for deal in active_deals):
        notes.append("Client used the monday item name where the Client column was blank or absent.")
    if duplicates:
        notes.append("Duplicate-ish deals are flagged for review and are not merged.")
    return AnalysisResult(
        metrics={
            "source_deal_count": len(deals),
            "deal_count": len(active_deals),
            "deals_with_valid_amount": valid_amounts,
            "total_pipeline_value_inr": total,
            "average_deal_value_inr": average,
        },
        quality=DataQualityReport(
            total_rows=len(deals),
            included_rows=valid_amounts,
            exclusions=dict(exclusions),
            normalization_notes=notes,
            duplicate_records=duplicates,
        ),
    )


def won_revenue(
    deals: Sequence[Record], *, usd_to_inr_rate: Decimal | None = None
) -> AnalysisResult:
    """Use valid Won deal value as a transparent revenue proxy.

    The Deals board has no accounting-recognition or payment data, so this metric
    deliberately labels itself as won deal value rather than recognized revenue.
    """
    total = Decimal("0")
    won_count = 0
    valid_amounts = 0
    won_deals: list[Record] = []
    exclusions: Counter[str] = Counter()
    for deal in deals:
        status = classify_deal_lifecycle(deal)
        if status == "unknown":
            exclusions["revenue_status:unknown"] += 1
            continue
        if status != "closed_won":
            exclusions["revenue_status:not_won"] += 1
            continue
        won_count += 1
        won_deals.append(deal)
        amount = _amount(deal, usd_to_inr_rate)
        if amount.is_valid and amount.value is not None:
            total += amount.value
            valid_amounts += 1
        else:
            exclusions[amount.reason or "invalid_currency"] += 1

    average = total / valid_amounts if valid_amounts else None
    duplicates = _duplicate_pairs(won_deals, usd_to_inr_rate)
    return AnalysisResult(
        metrics={
            "source_deal_count": len(deals),
            "won_deal_count": won_count,
            "won_deals_with_valid_amount": valid_amounts,
            "won_deal_value_inr": total,
            "average_won_deal_value_inr": average,
        },
        quality=DataQualityReport(
            total_rows=len(deals),
            included_rows=valid_amounts,
            exclusions=dict(exclusions),
            normalization_notes=[
                "Won deal value is a bookings/revenue proxy, not accounting-recognized revenue or collected cash.",
                "Only canonical Won stages with valid amounts are included; amounts are normalized to INR base units.",
                "Duplicate-ish won deals are flagged for review and are not merged.",
            ],
            duplicate_records=duplicates,
        ),
    )


def stage_conversion(
    deals: Sequence[Record], *, stage_order: Sequence[str] = DEFAULT_STAGE_ORDER
) -> AnalysisResult:
    """Compute a caveated snapshot progression proxy from last observed stages."""
    ordered_stages = tuple(stage_order)
    lookup = {stage.casefold(): index for index, stage in enumerate(ordered_stages)}
    observed_last_stage_counts = [0 for _ in ordered_stages]
    exclusions: Counter[str] = Counter()
    for deal in deals:
        normalized_stage = normalize_stage(
            record_value(deal, "stage", "status", "deal_stage")
        )
        stage = normalized_stage.value
        if stage is None:
            exclusions["missing_stage"] += 1
            continue

        observed_stage = stage
        if stage.casefold() == "lost":
            last_reached = text_value(
                record_value(deal, "last_reached_stage", "last_stage_before_loss")
            )
            history = record_value(deal, "stage_history", "stage_history_values")
            history_was_supplied = last_reached is not None or (
                isinstance(history, Sequence)
                and not isinstance(history, (str, bytes))
                and bool(history)
            )
            if last_reached is None and isinstance(history, Sequence) and not isinstance(
                history, (str, bytes)
            ):
                recognized_history: list[str] = []
                for history_entry in history:
                    if isinstance(history_entry, Mapping):
                        entry = text_value(
                            history_entry.get("stage")
                            or history_entry.get("status")
                            or history_entry.get("name")
                        )
                    else:
                        entry = text_value(history_entry)
                    normalized_entry = normalize_stage(entry).value
                    if normalized_entry is not None and normalized_entry.casefold() in lookup:
                        recognized_history.append(normalized_entry)
                if recognized_history:
                    last_reached = max(
                        recognized_history, key=lambda value: lookup[value.casefold()]
                    )
            if last_reached is None:
                exclusions[
                    "unknown_lost_stage_history"
                    if history_was_supplied
                    else "lost_without_stage_history"
                ] += 1
                continue
            observed_stage = last_reached

        if observed_stage.casefold() not in lookup:
            exclusions["unknown_stage"] += 1
        else:
            observed_last_stage_counts[lookup[observed_stage.casefold()]] += 1

    proxy_counts = {
        stage: sum(observed_last_stage_counts[index:])
        for index, stage in enumerate(ordered_stages)
    }
    proxy_rates: dict[str, Decimal | None] = {}
    for index in range(len(ordered_stages) - 1):
        current_stage = ordered_stages[index]
        next_stage = ordered_stages[index + 1]
        denominator = proxy_counts[current_stage]
        proxy_rates[f"{current_stage}->{next_stage}"] = (
            (Decimal(proxy_counts[next_stage]) * 100 / denominator).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )
            if denominator
            else None
        )
    included = sum(observed_last_stage_counts)
    return AnalysisResult(
        metrics={
            "observed_last_stage_counts": dict(
                zip(ordered_stages, observed_last_stage_counts, strict=True)
            ),
            "stage_progression_proxy_counts": proxy_counts,
            "stage_progression_proxy_rates": proxy_rates,
            "methodology": "snapshot_progression_proxy",
        },
        quality=DataQualityReport(
            total_rows=len(deals),
            included_rows=included,
            exclusions=dict(exclusions),
            normalization_notes=[
                "This stage-progression proxy uses current or last observed stage; it is not historical conversion.",
                "Lost deals without stage history are excluded from proxy denominators and reported as a quality issue.",
            ],
        ),
    )


def pipeline_by_sector(
    deals: Sequence[Record], *, usd_to_inr_rate: Decimal | None = None
) -> AnalysisResult:
    """Cut deal counts and valid pipeline amounts by normalized sector."""
    sectors: dict[str, dict[str, object]] = defaultdict(
        lambda: {"deal_count": 0, "total_value_inr": Decimal("0")}
    )
    exclusions: Counter[str] = Counter()
    valid_amounts = 0
    for deal in deals:
        status = classify_deal_lifecycle(deal)
        if status != "active":
            exclusions[f"pipeline_status:{status}"] += 1
            continue
        sector = normalize_sector(record_value(deal, "sector", "industry", "vertical"))
        label = sector.value or "Unclassified"
        sectors[label]["deal_count"] = int(sectors[label]["deal_count"]) + 1
        if not sector.is_valid:
            exclusions[f"sector:{sector.reason or 'low_confidence_sector'}"] += 1
        amount = _amount(deal, usd_to_inr_rate)
        if amount.is_valid and amount.value is not None:
            sectors[label]["total_value_inr"] = (
                Decimal(sectors[label]["total_value_inr"]) + amount.value
            )
            valid_amounts += 1
        else:
            exclusions[f"amount:{amount.reason or 'invalid_currency'}"] += 1
    return AnalysisResult(
        metrics={
            "sectors": {key: sectors[key] for key in sorted(sectors)},
            "source_deal_count": len(deals),
            "active_deal_count": sum(
                int(values["deal_count"]) for values in sectors.values()
            ),
            "included_row_basis": "rows_with_valid_amount",
        },
        quality=DataQualityReport(
            total_rows=len(deals),
            included_rows=valid_amounts,
            exclusions=dict(exclusions),
            normalization_notes=[
                "Sector pipeline includes active opportunities only; terminal and unknown-stage rows are excluded.",
                "Sector aliases and conservative fuzzy matching are applied; uncertain labels remain Unclassified.",
                "included_rows counts rows with a valid amount; field-scoped sector issues do not independently remove rows.",
            ],
        ),
    )


def missing_close_date_quality(deals: Sequence[Record]) -> AnalysisResult:
    """Measure missing close dates separately from malformed dates."""
    exclusions: Counter[str] = Counter()
    valid = 0
    for deal in deals:
        close_date = normalize_date(
            record_value(deal, "close_date", "expected_close_date", "closed_date")
        )
        if close_date.is_valid:
            valid += 1
        else:
            exclusions[close_date.reason or "invalid_date"] += 1
    total = len(deals)
    missing = exclusions["missing_value"]
    rate = (
        (Decimal(missing) * 100 / total).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        if total
        else Decimal("0.00")
    )
    return AnalysisResult(
        metrics={
            "valid_close_date_count": valid,
            "missing_close_date_count": missing,
            "invalid_close_date_count": exclusions["invalid_date"],
            "missing_close_date_rate": rate,
        },
        quality=DataQualityReport(
            total_rows=total,
            included_rows=valid,
            exclusions=dict(exclusions),
            normalization_notes=["Missing and malformed close dates are reported separately."],
        ),
    )
