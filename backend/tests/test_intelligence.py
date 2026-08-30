from datetime import date
from decimal import Decimal

from app.intelligence.cross_board import won_deals_without_work_orders
from app.intelligence.operations_metrics import average_work_order_completion_time
from app.intelligence.pipeline_metrics import (
    missing_close_date_quality,
    pipeline_health,
    pipeline_by_sector,
    stage_conversion,
)
from tests.fixtures.business_records import DEALS, WORK_ORDERS


def test_pipeline_health_totals_valid_amounts_and_flags_duplicates_without_merging() -> None:
    """Invalid amounts or duplicate-ish rows must not be silently hidden in pipeline totals."""
    result = pipeline_health(DEALS)

    assert result.metrics == {
        "deal_count": 4,
        "deals_with_valid_amount": 3,
        "total_pipeline_value_inr": Decimal("22020000"),
        "average_deal_value_inr": Decimal("7340000"),
    }
    assert result.quality.total_rows == 4
    assert result.quality.included_rows == 3
    assert result.quality.exclusions == {"invalid_currency": 1}
    assert result.quality.duplicate_records == [("d-1", "d-2")]


def test_stage_conversion_uses_reached_stage_denominators_and_exposes_sparse_stages() -> None:
    """Dividing mutually exclusive stage counts directly produces false funnel conversion."""
    deals = [
        {"id": "1", "stage": "Lead"},
        {"id": "2", "stage": "Qualified"},
        {"id": "3", "stage": "Proposal"},
        {"id": "4", "stage": "Won"},
        {"id": "5", "stage": "Lost"},
        {"id": "6", "stage": "unknown"},
    ]

    result = stage_conversion(deals, stage_order=("Lead", "Qualified", "Proposal", "Won"))

    assert result.metrics["reached_stage_counts"] == {
        "Lead": 4,
        "Qualified": 3,
        "Proposal": 2,
        "Won": 1,
    }
    assert result.metrics["conversion_rates"] == {
        "Lead->Qualified": Decimal("75.00"),
        "Qualified->Proposal": Decimal("66.67"),
        "Proposal->Won": Decimal("50.00"),
    }
    assert result.quality.exclusions == {"terminal_lost_stage": 1, "unknown_stage": 1}


def test_pipeline_by_sector_normalizes_aliases_and_keeps_unclassified_visible() -> None:
    """Dropping uncertain sectors makes sector cuts look cleaner than their source data."""
    result = pipeline_by_sector(DEALS)

    assert result.metrics["sectors"] == {
        "Energy": {"deal_count": 1, "total_value_inr": Decimal("20000000")},
        "Technology": {"deal_count": 2, "total_value_inr": Decimal("2020000")},
        "Unclassified": {"deal_count": 1, "total_value_inr": Decimal("0")},
    }
    assert result.quality.total_rows == 4
    assert result.quality.included_rows == 3
    assert result.quality.exclusions == {
        "invalid_currency": 1,
        "low_confidence_sector": 1,
    }


def test_missing_close_date_quality_separates_missing_from_malformed() -> None:
    """Combining missing and malformed close dates hides the remediation needed."""
    result = missing_close_date_quality(DEALS)

    assert result.metrics == {
        "valid_close_date_count": 2,
        "missing_close_date_count": 1,
        "invalid_close_date_count": 1,
        "missing_close_date_rate": Decimal("25.00"),
    }
    assert result.quality.included_rows == 2
    assert result.quality.exclusions == {"missing_value": 1, "invalid_date": 1}


def test_average_work_order_completion_time_excludes_missing_and_negative_durations() -> None:
    """Invalid chronology and unfinished orders must not distort cycle time."""
    result = average_work_order_completion_time(WORK_ORDERS)

    assert result.metrics == {
        "completed_work_order_count": 1,
        "average_completion_days": Decimal("10.00"),
        "minimum_completion_days": 10,
        "maximum_completion_days": 10,
    }
    assert result.quality.total_rows == 3
    assert result.quality.included_rows == 1
    assert result.quality.exclusions == {"negative_completion_duration": 1, "missing_value": 1}


def test_won_deals_without_work_orders_matches_relation_then_normalized_client() -> None:
    """A won deal linked by relation or normalized client must not be reported as unfulfilled."""
    deals = [
        {"id": "d-1", "name": "First", "client": "Acme, Inc.", "stage": "Won"},
        {"id": "d-2", "name": "Second", "client": "Beta Ltd", "stage": "Won"},
        {"id": "d-3", "name": "Third", "client": "Gamma", "stage": "Won"},
        {"id": "d-4", "name": "Open", "client": "Delta", "stage": "Proposal"},
    ]
    work_orders = [
        {"id": "wo-1", "deal_id": "d-1", "client": "Different"},
        {"id": "wo-2", "deal_id": "", "client": " beta ltd "},
    ]

    result = won_deals_without_work_orders(deals, work_orders)

    assert result.metrics == {
        "won_deal_count": 3,
        "matched_work_order_count": 2,
        "missing_work_order_count": 1,
        "missing_work_orders": [{"deal_id": "d-3", "deal_name": "Third", "client": "Gamma"}],
    }
    assert result.quality.total_rows == 4
    assert result.quality.included_rows == 3
    assert result.quality.exclusions == {"not_won": 1}


def test_won_deal_gap_reports_missing_match_keys_as_quality_exclusions() -> None:
    """A won deal with neither ID nor client cannot be confidently cross-board matched."""
    result = won_deals_without_work_orders(
        [{"id": "", "name": "Unkeyed", "client": "", "stage": "Won"}], []
    )

    assert result.metrics["won_deal_count"] == 1
    assert result.metrics["missing_work_order_count"] == 0
    assert result.quality.included_rows == 0
    assert result.quality.exclusions == {"missing_match_key": 1}


def test_intelligence_accepts_dates_as_typed_values_after_transport_normalization() -> None:
    """Metrics should retain compatibility with already-normalized internal values."""
    result = average_work_order_completion_time(
        [{"id": "wo", "start_date": date(2026, 1, 1), "completion_date": date(2026, 1, 6)}]
    )

    assert result.metrics["average_completion_days"] == Decimal("5.00")
