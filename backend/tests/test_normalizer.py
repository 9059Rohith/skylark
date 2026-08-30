from datetime import date
from decimal import Decimal

import pytest

from app.cleaning.normalizer import (
    normalize_currency,
    normalize_date,
    normalize_sector,
)
from app.cleaning.quality_report import DataQualityReport
from app.cleaning.rules import DuplicateCandidate, find_duplicate_candidates


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("2026-08-30", date(2026, 8, 30)),
        ("30/08/2026", date(2026, 8, 30)),
        ("08-30-2026", date(2026, 8, 30)),
        ("30 August 2026", date(2026, 8, 30)),
        ("August 30, 2026", date(2026, 8, 30)),
    ],
)
def test_normalize_date_accepts_supported_shapes(raw_value: str, expected: date) -> None:
    """Changing a supported format or interpreting it incorrectly breaks date metrics."""
    normalized = normalize_date(raw_value)

    assert normalized.value == expected
    assert normalized.is_valid is True
    assert normalized.reason is None


def test_normalize_date_treats_ambiguous_slashes_as_day_first() -> None:
    """Changing the documented slash convention silently shifts reporting periods."""
    normalized = normalize_date("03/04/2026")

    assert normalized.value == date(2026, 4, 3)
    assert normalized.is_valid is True


def test_normalize_date_treats_ambiguous_dashes_as_month_first() -> None:
    """Changing the documented dash convention silently shifts reporting periods."""
    normalized = normalize_date("03-04-2026")

    assert normalized.value == date(2026, 3, 4)
    assert normalized.is_valid is True


@pytest.mark.parametrize("raw_value", [None, "", "   "])
def test_normalize_date_flags_missing_values(raw_value: object) -> None:
    """Treating an absent date as a real date would make exclusions invisible."""
    normalized = normalize_date(raw_value)

    assert normalized.value is None
    assert normalized.is_valid is False
    assert normalized.reason == "missing_value"


@pytest.mark.parametrize("raw_value", ["2026-02-30", "not a date"])
def test_normalize_date_flags_invalid_values(raw_value: str) -> None:
    """Accepting malformed dates would place records in the wrong time period."""
    normalized = normalize_date(raw_value)

    assert normalized.value is None
    assert normalized.is_valid is False
    assert normalized.reason == "invalid_date"


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("INR 1,25,000", Decimal("125000")),
        ("₹12.50 L", Decimal("1250000")),
        ("2 Cr", Decimal("20000000")),
        ("750k", Decimal("750000")),
    ],
)
def test_normalize_currency_converts_inr_values_to_base_units(
    raw_value: str, expected: Decimal
) -> None:
    """Dropping a supported multiplier produces materially wrong pipeline totals."""
    normalized = normalize_currency(raw_value, usd_to_inr_rate=None)

    assert normalized.value == expected
    assert normalized.is_valid is True
    assert normalized.reason is None


def test_normalize_currency_converts_dollars_with_the_supplied_rate() -> None:
    """Ignoring the supplied exchange rate misstates INR pipeline value."""
    normalized = normalize_currency("$1,250", usd_to_inr_rate=Decimal("83.25"))

    assert normalized.value == Decimal("104062.50")
    assert normalized.is_valid is True
    assert normalized.reason is None


def test_normalize_currency_rejects_dollars_without_an_exchange_rate() -> None:
    """Treating USD as INR when no rate exists hides a material data-quality issue."""
    normalized = normalize_currency("$1,250", usd_to_inr_rate=None)

    assert normalized.value is None
    assert normalized.is_valid is False
    assert normalized.reason == "usd_to_inr_rate_required"


@pytest.mark.parametrize("raw_value", [None, "", "  "])
def test_normalize_currency_flags_missing_values(raw_value: object) -> None:
    """Treating an absent amount as zero hides a record exclusion."""
    normalized = normalize_currency(raw_value, usd_to_inr_rate=Decimal("83"))

    assert normalized.value is None
    assert normalized.is_valid is False
    assert normalized.reason == "missing_value"


def test_normalize_currency_flags_invalid_values() -> None:
    """Accepting non-numeric amounts corrupts deterministic arithmetic."""
    normalized = normalize_currency("many rupees", usd_to_inr_rate=Decimal("83"))

    assert normalized.value is None
    assert normalized.is_valid is False
    assert normalized.reason == "invalid_currency"


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("IT Services", "Technology"),
        ("BFSI", "Financial Services"),
        ("health care", "Healthcare"),
    ],
)
def test_normalize_sector_maps_known_aliases(raw_value: str, expected: str) -> None:
    """Removing an alias fragments a single business sector across reports."""
    normalized = normalize_sector(raw_value)

    assert normalized.value == expected
    assert normalized.is_valid is True
    assert normalized.reason is None


def test_normalize_sector_accepts_high_confidence_fuzzy_match() -> None:
    """Failing to recover a near-exact sector typo needlessly unclassifies data."""
    normalized = normalize_sector("technlogy")

    assert normalized.value == "Technology"
    assert normalized.is_valid is True
    assert normalized.reason is None


def test_normalize_sector_preserves_low_confidence_uncertainty() -> None:
    """Classifying an unrelated label as a sector would hide uncertainty."""
    normalized = normalize_sector("garden supplies")

    assert normalized.value == "Unclassified"
    assert normalized.is_valid is False
    assert normalized.reason == "low_confidence_sector"


@pytest.mark.parametrize("raw_value", [None, "", "  "])
def test_normalize_sector_flags_missing_values(raw_value: object) -> None:
    """Missing sectors must remain visible instead of becoming a confident category."""
    normalized = normalize_sector(raw_value)

    assert normalized.value == "Unclassified"
    assert normalized.is_valid is False
    assert normalized.reason == "missing_value"


def test_quality_report_merge_preserves_counts_notes_and_duplicate_flags() -> None:
    """Dropping a partial report would understate data-quality exclusions."""
    first = DataQualityReport(
        total_rows=4,
        included_rows=3,
        exclusions={"missing_value": 1},
        normalization_notes=["Dates use day-first slash parsing."],
        duplicate_records=[("deal-1", "deal-2")],
    )
    second = DataQualityReport(
        total_rows=2,
        included_rows=1,
        exclusions={"missing_value": 1, "invalid_currency": 1},
        normalization_notes=["USD requires an exchange rate."],
        duplicate_records=[("deal-4", "deal-5")],
    )

    merged = first.merge(second)

    assert merged.total_rows == 6
    assert merged.included_rows == 4
    assert merged.exclusions == {"missing_value": 2, "invalid_currency": 1}
    assert merged.normalization_notes == [
        "Dates use day-first slash parsing.",
        "USD requires an exchange rate.",
    ]
    assert merged.duplicate_records == [("deal-1", "deal-2"), ("deal-4", "deal-5")]


def test_find_duplicate_candidates_flags_similar_records_without_merging_them() -> None:
    """Missing a duplicate-ish pair makes analysts overcount possible duplicate deals."""
    records = [
        DuplicateCandidate(
            record_id="deal-1",
            client_name="Acme, Inc.",
            amount=Decimal("1000000"),
            close_date=date(2026, 8, 10),
        ),
        DuplicateCandidate(
            record_id="deal-2",
            client_name=" acme inc ",
            amount=Decimal("1020000"),
            close_date=date(2026, 8, 17),
        ),
    ]

    duplicates = find_duplicate_candidates(records)

    assert len(records) == 2
    assert [(item.record_id, item.matching_record_id) for item in duplicates] == [
        ("deal-1", "deal-2")
    ]


@pytest.mark.parametrize(
    "second_record",
    [
        DuplicateCandidate(
            record_id="deal-2",
            client_name="Acme Inc",
            amount=Decimal("1100000"),
            close_date=date(2026, 8, 17),
        ),
        DuplicateCandidate(
            record_id="deal-2",
            client_name="Acme Inc",
            amount=Decimal("1000000"),
            close_date=date(2026, 9, 10),
        ),
        DuplicateCandidate(
            record_id="deal-2",
            client_name="Other Co",
            amount=Decimal("1000000"),
            close_date=date(2026, 8, 17),
        ),
    ],
)
def test_find_duplicate_candidates_requires_client_amount_and_date_agreement(
    second_record: DuplicateCandidate,
) -> None:
    """Flagging a pair when one duplicate signal disagrees creates false positives."""
    first_record = DuplicateCandidate(
        record_id="deal-1",
        client_name="Acme Inc",
        amount=Decimal("1000000"),
        close_date=date(2026, 8, 10),
    )

    assert find_duplicate_candidates([first_record, second_record]) == []
