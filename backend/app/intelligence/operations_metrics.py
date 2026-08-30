"""Deterministic work-order operational metrics."""

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from app.cleaning.normalizer import normalize_date
from app.cleaning.quality_report import DataQualityReport
from app.intelligence.records import Record, record_value
from app.intelligence.schemas import AnalysisResult


def average_work_order_completion_time(work_orders: Sequence[Record]) -> AnalysisResult:
    """Average non-negative elapsed calendar days for completed work orders."""
    durations: list[int] = []
    exclusions: Counter[str] = Counter()
    for work_order in work_orders:
        started = normalize_date(
            record_value(work_order, "start_date", "started_date", "created_date")
        )
        completed = normalize_date(
            record_value(work_order, "completion_date", "completed_date", "end_date")
        )
        if not started.is_valid or not completed.is_valid:
            reason = (
                started.reason if not started.is_valid else completed.reason
            ) or "invalid_date"
            exclusions[reason] += 1
            continue
        duration = (completed.value - started.value).days
        if duration < 0:
            exclusions["negative_completion_duration"] += 1
            continue
        durations.append(duration)
    average = (
        (Decimal(sum(durations)) / len(durations)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if durations
        else None
    )
    return AnalysisResult(
        metrics={
            "completed_work_order_count": len(durations),
            "average_completion_days": average,
            "minimum_completion_days": min(durations) if durations else None,
            "maximum_completion_days": max(durations) if durations else None,
        },
        quality=DataQualityReport(
            total_rows=len(work_orders),
            included_rows=len(durations),
            exclusions=dict(exclusions),
            normalization_notes=["Completion time is elapsed calendar days from start through completion."],
        ),
    )
