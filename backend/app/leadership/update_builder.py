"""Human-reviewed leadership update draft builder; it has no write action."""

from datetime import date
from decimal import Decimal
from collections.abc import Mapping, Sequence
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.cleaning import normalize_date
from app.cleaning.quality_report import DataQualityReport
from app.intelligence.operations_metrics import average_work_order_completion_time
from app.intelligence.schemas import AnalysisResult


class SectorSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector: str
    deal_count: int
    pipeline_value_inr: Decimal


class AtRiskItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_type: str
    record_id: str | None = None
    name: str | None = None
    reason: str


class LeadershipUpdate(BaseModel):
    """A typed draft that must be reviewed and copied by a human."""

    model_config = ConfigDict(frozen=True)

    headline_pipeline_value_inr: Decimal
    sector_breakdown: list[SectorSummary] = Field(default_factory=list)
    notable_at_risk: list[AtRiskItem] = Field(default_factory=list)
    quality: "LeadershipQuality"
    quality_footnote: str
    markdown: str


class LeadershipQuality(BaseModel):
    """Per-section reports; deliberately not merged across repeated source rows."""

    model_config = ConfigDict(frozen=True)

    pipeline: DataQualityReport
    sector: DataQualityReport
    gaps: DataQualityReport
    operational_risks: DataQualityReport


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal("0")


_RISKY_WORK_ORDER_STATUSES = {
    "blocked": "Blocked",
    "delayed": "Delayed",
    "at risk": "At Risk",
    "overdue": "Overdue",
    "pause struck": "Paused / Stuck",
}

_CONDITIONALLY_RISKY_STATUSES = {
    "not started": "Not Started",
    "details pending from client": "Details Pending",
}


def _risky_status(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    key = " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())
    return _RISKY_WORK_ORDER_STATUSES.get(key)


def build_leadership_update(
    pipeline: AnalysisResult,
    sectors: AnalysisResult,
    gaps: AnalysisResult,
    *,
    work_orders: Sequence[Mapping[str, Any]] = (),
    as_of: date | None = None,
) -> LeadershipUpdate:
    """Build a deterministic draft from aggregate analyses only."""
    headline = _decimal(pipeline.metrics.get("total_pipeline_value_inr"))
    sector_rows = [
        SectorSummary(
            sector=str(sector),
            deal_count=int(values.get("deal_count", 0)),
            pipeline_value_inr=_decimal(values.get("total_value_inr")),
        )
        for sector, values in sorted(
            dict(sectors.metrics.get("sectors", {})).items(), key=lambda row: row[0]
        )
        if isinstance(values, dict)
    ]
    at_risk = [
        AtRiskItem(
            record_type="deal",
            record_id=item.get("deal_id"),
            name=item.get("deal_name") or item.get("client"),
            reason="Won deal has no matching work order",
        )
        for item in gaps.metrics.get("missing_work_orders", [])
        if isinstance(item, dict)
    ][:5]
    for work_order in work_orders:
        risky_status = _risky_status(work_order.get("status"))
        status_key = " ".join(
            re.sub(
                r"[^a-z0-9]+", " ", str(work_order.get("status") or "").casefold()
            ).split()
        )
        expected_end = normalize_date(work_order.get("expected_end_date"))
        overdue_status = _CONDITIONALLY_RISKY_STATUSES.get(status_key)
        started = normalize_date(work_order.get("start_date"))
        completed = normalize_date(work_order.get("completion_date"))
        if risky_status is not None:
            reason = f"Work order status is {risky_status}"
        elif (
            overdue_status is not None
            and as_of is not None
            and expected_end.is_valid
            and expected_end.value is not None
            and expected_end.value < as_of
        ):
            reason = f"Work order is overdue with status {overdue_status}"
        elif overdue_status is not None:
            continue
        elif completed.is_valid:
            if (
                started.is_valid
                and started.value is not None
                and completed.value is not None
                and completed.value < started.value
            ):
                reason = "Completion date precedes start date"
            else:
                continue
        else:
            reason = "Work order has no valid completion date"
        at_risk.append(
            AtRiskItem(
                record_type="work_order",
                record_id=str(work_order.get("id")) if work_order.get("id") else None,
                name=str(work_order.get("name")) if work_order.get("name") else None,
                reason=reason,
            )
        )
        if len(at_risk) >= 5:
            break
    excluded = pipeline.quality.total_rows - pipeline.quality.included_rows
    operational_quality = average_work_order_completion_time(work_orders).quality
    quality = LeadershipQuality(
        pipeline=pipeline.quality,
        sector=sectors.quality,
        gaps=gaps.quality,
        operational_risks=operational_quality,
    )
    quality_footnote = " ".join(
        (
            f"Pipeline quality: {excluded} of {pipeline.quality.total_rows} pipeline rows were excluded.",
            f"Sector quality: {sectors.quality.included_rows} of {sectors.quality.total_rows} rows had valid amounts.",
            f"Gap-analysis quality: {gaps.quality.included_rows} of {gaps.quality.total_rows} deal/work-order evidence rows were usable.",
            f"Operational-risk quality: {operational_quality.included_rows} of {operational_quality.total_rows} work orders had valid completion chronology.",
        )
    )
    sector_lines = [
        f"- {row.sector}: INR {row.pipeline_value_inr:,} across {row.deal_count} deal(s)"
        for row in sector_rows
    ] or ["- No valid sector aggregates were available."]
    risk_lines = [
        f"- {row.name or row.record_id or 'Unnamed deal'}: {row.reason}"
        for row in at_risk
    ] or ["- No unmatched won deals were identified."]
    markdown = "\n".join(
        [
            "# Leadership update (draft)",
            "",
            f"**Headline pipeline:** INR {headline:,}",
            "",
            "## Sector breakdown",
            *sector_lines,
            "",
            "## Notable at-risk items",
            *risk_lines,
            "",
            f"_Data quality: {quality_footnote}_",
        ]
    )
    return LeadershipUpdate(
        headline_pipeline_value_inr=headline,
        sector_breakdown=sector_rows,
        notable_at_risk=at_risk,
        quality=quality,
        quality_footnote=quality_footnote,
        markdown=markdown,
    )
