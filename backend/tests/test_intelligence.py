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
from app.monday.schemas import ColumnSchema
from app.monday.tools import normalize_column_value
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


def test_stage_conversion_returns_a_caveated_snapshot_progression_proxy() -> None:
    """Snapshot stage distribution must not be labeled as historical conversion."""
    deals = [
        {"id": "1", "stage": "Lead"},
        {"id": "2", "stage": "Qualified"},
        {"id": "3", "stage": "Proposal"},
        {"id": "4", "stage": "Won"},
        {"id": "5", "stage": "Lost"},
        {"id": "6", "stage": "unknown"},
    ]

    result = stage_conversion(deals, stage_order=("Lead", "Qualified", "Proposal", "Won"))

    assert result.metrics["stage_progression_proxy_counts"] == {
        "Lead": 4,
        "Qualified": 3,
        "Proposal": 2,
        "Won": 1,
    }
    assert result.metrics["stage_progression_proxy_rates"] == {
        "Lead->Qualified": Decimal("75.00"),
        "Qualified->Proposal": Decimal("66.67"),
        "Proposal->Won": Decimal("50.00"),
    }
    assert "conversion_rates" not in result.metrics
    assert result.metrics["methodology"] == "snapshot_progression_proxy"
    assert result.quality.exclusions == {
        "lost_without_stage_history": 1,
        "unknown_stage": 1,
    }
    assert any(
        "not historical conversion" in note.casefold()
        for note in result.quality.normalization_notes
    )


def test_stage_progression_proxy_uses_lost_deal_history_when_available() -> None:
    """Lost deals with an observed last stage must contribute to progression reach."""
    deals = [
        {"id": "1", "stage": "Lost", "last_reached_stage": "Proposal"},
        {"id": "2", "stage": "Lost", "stage_history": ["Lead", "Qualified"]},
        {"id": "3", "stage": "Won"},
    ]

    result = stage_conversion(deals, stage_order=("Lead", "Qualified", "Proposal", "Won"))

    assert result.metrics["observed_last_stage_counts"] == {
        "Lead": 0,
        "Qualified": 1,
        "Proposal": 1,
        "Won": 1,
    }
    assert result.metrics["stage_progression_proxy_counts"] == {
        "Lead": 3,
        "Qualified": 3,
        "Proposal": 2,
        "Won": 1,
    }
    assert result.quality.included_rows == 3
    assert result.quality.exclusions == {}


def test_many_lost_deals_cannot_appear_as_uncaveated_exact_conversion() -> None:
    """Survivorship bias must stay visible when loss history is unavailable."""
    deals = [
        *({"id": f"lost-{index}", "stage": "Lost"} for index in range(20)),
        {"id": "won", "stage": "Won"},
    ]

    result = stage_conversion(deals, stage_order=("Lead", "Qualified", "Proposal", "Won"))

    assert "conversion_rates" not in result.metrics
    assert result.metrics["methodology"] == "snapshot_progression_proxy"
    assert result.quality.included_rows == 1
    assert result.quality.exclusions == {"lost_without_stage_history": 20}
    assert any(
        "lost deals without stage history are excluded" in note.casefold()
        for note in result.quality.normalization_notes
    )


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
        "amount:invalid_currency": 1,
        "sector:low_confidence_sector": 1,
    }
    assert result.metrics["included_row_basis"] == "rows_with_valid_amount"
    assert any(
        "included_rows counts rows with a valid amount" in note
        for note in result.quality.normalization_notes
    )


def test_pipeline_by_sector_uses_field_scoped_missing_value_issues() -> None:
    """Shared reason names must not imply sector and amount issues dropped two rows."""
    result = pipeline_by_sector([{"id": "d-1", "sector": "", "amount": ""}])

    assert result.quality.total_rows == 1
    assert result.quality.included_rows == 0
    assert result.quality.exclusions == {
        "sector:missing_value": 1,
        "amount:missing_value": 1,
    }
    assert result.metrics["included_row_basis"] == "rows_with_valid_amount"


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
    assert result.quality.total_rows == 6
    assert result.quality.included_rows == 5
    assert result.quality.exclusions == {"not_won": 1}


def test_transport_relation_id_list_matches_won_deal_without_stringifying_sequence() -> None:
    """Transport relation arrays must remain usable as exact cross-board deal IDs."""
    relation_ids = normalize_column_value(
        {
            "id": "deal_id",
            "type": "board_relation",
            "text": "Acme expansion",
            "value": '{"linkedPulseIds": [{"linkedPulseId": "d-1"}]}',
        },
        ColumnSchema(id="deal_id", title="Deal", type="board_relation"),
    )

    result = won_deals_without_work_orders(
        [{"id": "d-1", "name": "Acme", "client": "", "stage": "Won"}],
        [{"id": "wo-1", "deal_id": relation_ids, "client": ""}],
    )

    assert relation_ids == ["d-1"]
    assert result.metrics["matched_work_order_count"] == 1
    assert result.metrics["missing_work_order_count"] == 0


def test_won_deal_gap_reports_missing_match_keys_as_quality_exclusions() -> None:
    """A won deal with neither ID nor client cannot be confidently cross-board matched."""
    result = won_deals_without_work_orders(
        [{"id": "", "name": "Unkeyed", "client": "", "stage": "Won"}], []
    )

    assert result.metrics["won_deal_count"] == 1
    assert result.metrics["missing_work_order_count"] == 0
    assert result.quality.included_rows == 0
    assert result.quality.exclusions == {"missing_match_key": 1}


def test_cross_board_quality_excludes_work_orders_without_any_match_key() -> None:
    """Unkeyed work orders are source rows but not usable cross-board evidence."""
    result = won_deals_without_work_orders(
        [{"id": "d-1", "name": "Acme", "client": "Acme", "stage": "Won"}],
        [
            {"id": "wo-1", "deal_id": "d-1", "client": ""},
            {"id": "wo-2", "deal_id": "", "client": "  "},
        ],
    )

    assert result.quality.total_rows == 3
    assert result.quality.included_rows == 2
    assert result.quality.exclusions == {"work_order:missing_match_key": 1}


def test_intelligence_accepts_dates_as_typed_values_after_transport_normalization() -> None:
    """Metrics should retain compatibility with already-normalized internal values."""
    result = average_work_order_completion_time(
        [{"id": "wo", "start_date": date(2026, 1, 1), "completion_date": date(2026, 1, 6)}]
    )

    assert result.metrics["average_completion_days"] == Decimal("5.00")
