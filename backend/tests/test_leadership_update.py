from decimal import Decimal

from app.cleaning import DataQualityReport
from app.intelligence import AnalysisResult
from app.leadership.update_builder import LeadershipUpdate, build_leadership_update


def test_leadership_update_is_a_typed_reviewable_draft_with_no_send_action() -> None:
    """Flattening the draft or omitting caveats makes leadership review unsafe."""
    pipeline = AnalysisResult(
        metrics={"total_pipeline_value_inr": Decimal("21000000")},
        quality=DataQualityReport(
            total_rows=3,
            included_rows=2,
            exclusions={"invalid_currency": 1},
        ),
    )
    sectors = AnalysisResult(
        metrics={
            "sectors": {
                "Energy": {"deal_count": 1, "total_value_inr": Decimal("20000000")},
                "Technology": {"deal_count": 1, "total_value_inr": Decimal("1000000")},
            }
        },
        quality=DataQualityReport(total_rows=2, included_rows=2),
    )
    gaps = AnalysisResult(
        metrics={
            "missing_work_orders": [
                {"deal_id": "d-2", "deal_name": "Beta rollout", "client": "Beta"}
            ]
        },
        quality=DataQualityReport(total_rows=2, included_rows=2),
    )

    draft = build_leadership_update(
        pipeline,
        sectors,
        gaps,
        work_orders=[
            {
                "id": "wo-9",
                "name": "Delayed activation",
                "start_date": "2026-08-01",
                "completion_date": "",
            }
        ],
    )

    assert isinstance(draft, LeadershipUpdate)
    assert draft.headline_pipeline_value_inr == Decimal("21000000")
    assert [row.sector for row in draft.sector_breakdown] == ["Energy", "Technology"]
    assert draft.notable_at_risk[0].record_id == "d-2"
    assert draft.notable_at_risk[1].record_id == "wo-9"
    assert draft.notable_at_risk[1].record_type == "work_order"
    assert draft.quality.pipeline == pipeline.quality
    assert draft.quality.sector == sectors.quality
    assert draft.quality.gaps == gaps.quality
    assert draft.quality.operational_risks.total_rows == 1
    assert draft.quality.operational_risks.exclusions == {"missing_value": 1}
    assert "1 of 3 pipeline rows were excluded" in draft.quality_footnote
    assert draft.markdown.startswith("# Leadership update (draft)")
    assert "Pipeline quality:" in draft.markdown
    assert "Gap-analysis quality:" in draft.markdown
    assert not hasattr(draft, "send")
