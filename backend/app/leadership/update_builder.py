"""Human-reviewed leadership update draft builder; it has no write action."""

from decimal import Decimal
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.cleaning import normalize_date
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
    quality_footnote: str
    markdown: str


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal("0")


def build_leadership_update(
    pipeline: AnalysisResult,
    sectors: AnalysisResult,
    gaps: AnalysisResult,
    *,
    work_orders: Sequence[Mapping[str, Any]] = (),
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
        started = normalize_date(work_order.get("start_date"))
        completed = normalize_date(work_order.get("completion_date"))
        if completed.is_valid:
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
    quality_footnote = (
        f"{excluded} of {pipeline.quality.total_rows} pipeline rows were excluded "
        "from the headline metric based on normalization validity."
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
        quality_footnote=quality_footnote,
        markdown=markdown,
    )
