"""Deterministic deals-pipeline metrics with explicit quality accounting."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from app.cleaning.normalizer import normalize_currency, normalize_date, normalize_sector
from app.cleaning.quality_report import DataQualityReport
from app.cleaning.rules import DuplicateCandidate, find_duplicate_candidates
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
    """Calculate headline pipeline value without removing duplicate-ish source rows."""
    total = Decimal("0")
    valid_amounts = 0
    exclusions: Counter[str] = Counter()
    for deal in deals:
        amount = _amount(deal, usd_to_inr_rate)
        if amount.is_valid and amount.value is not None:
            total += amount.value
            valid_amounts += 1
        else:
            exclusions[amount.reason or "invalid_currency"] += 1
    average = total / valid_amounts if valid_amounts else None
    duplicates = _duplicate_pairs(deals, usd_to_inr_rate)
    notes = ["Amounts are normalized to INR base units."]
    if duplicates:
        notes.append("Duplicate-ish deals are flagged for review and are not merged.")
    return AnalysisResult(
        metrics={
            "deal_count": len(deals),
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


def stage_conversion(
    deals: Sequence[Record], *, stage_order: Sequence[str] = DEFAULT_STAGE_ORDER
) -> AnalysisResult:
    """Compute snapshot funnel conversion from counts that reached each stage."""
    ordered_stages = tuple(stage_order)
    lookup = {stage.casefold(): index for index, stage in enumerate(ordered_stages)}
    current_counts = [0 for _ in ordered_stages]
    exclusions: Counter[str] = Counter()
    for deal in deals:
        stage = text_value(record_value(deal, "stage", "status", "deal_stage"))
        if stage is None:
            exclusions["missing_stage"] += 1
        elif stage.casefold() == "lost":
            exclusions["terminal_lost_stage"] += 1
        elif stage.casefold() not in lookup:
            exclusions["unknown_stage"] += 1
        else:
            current_counts[lookup[stage.casefold()]] += 1

    reached_counts = {
        stage: sum(current_counts[index:])
        for index, stage in enumerate(ordered_stages)
    }
    conversion_rates: dict[str, Decimal | None] = {}
    for index in range(len(ordered_stages) - 1):
        current_stage = ordered_stages[index]
        next_stage = ordered_stages[index + 1]
        denominator = reached_counts[current_stage]
        conversion_rates[f"{current_stage}->{next_stage}"] = (
            (Decimal(reached_counts[next_stage]) * 100 / denominator).quantize(
                _TWO_PLACES, rounding=ROUND_HALF_UP
            )
            if denominator
            else None
        )
    included = sum(current_counts)
    return AnalysisResult(
        metrics={
            "stage_counts": dict(zip(ordered_stages, current_counts, strict=True)),
            "reached_stage_counts": reached_counts,
            "conversion_rates": conversion_rates,
        },
        quality=DataQualityReport(
            total_rows=len(deals),
            included_rows=included,
            exclusions=dict(exclusions),
            normalization_notes=[
                "Conversion is a snapshot of records at or beyond adjacent ordered stages."
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
        sector = normalize_sector(record_value(deal, "sector", "industry", "vertical"))
        label = sector.value or "Unclassified"
        sectors[label]["deal_count"] = int(sectors[label]["deal_count"]) + 1
        if not sector.is_valid:
            exclusions[sector.reason or "low_confidence_sector"] += 1
        amount = _amount(deal, usd_to_inr_rate)
        if amount.is_valid and amount.value is not None:
            sectors[label]["total_value_inr"] = (
                Decimal(sectors[label]["total_value_inr"]) + amount.value
            )
            valid_amounts += 1
        else:
            exclusions[amount.reason or "invalid_currency"] += 1
    return AnalysisResult(
        metrics={"sectors": {key: sectors[key] for key in sorted(sectors)}},
        quality=DataQualityReport(
            total_rows=len(deals),
            included_rows=valid_amounts,
            exclusions=dict(exclusions),
            normalization_notes=[
                "Sector aliases and conservative fuzzy matching are applied; uncertain labels remain Unclassified."
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
