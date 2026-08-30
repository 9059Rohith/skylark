"""Explicit normalization rules, taxonomies, and duplicate-review rules."""

from collections.abc import Sequence
from decimal import Decimal
import re

from app.cleaning.schemas import DuplicateCandidate, DuplicateFlag


SECTOR_FUZZY_THRESHOLD = 90.0
DUPLICATE_AMOUNT_TOLERANCE = Decimal("0.05")
DUPLICATE_CLOSE_DATE_WINDOW_DAYS = 14

SECTOR_ALIASES = {
    "technology": "Technology",
    "it": "Technology",
    "it services": "Technology",
    "information technology": "Technology",
    "software": "Technology",
    "financial services": "Financial Services",
    "bfsi": "Financial Services",
    "banking": "Financial Services",
    "insurance": "Financial Services",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "energy": "Energy",
    "energy sector": "Energy",
    "manufacturing": "Manufacturing",
    "retail": "Retail",
    "professional services": "Professional Services",
}


def _normalized_client_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return normalized or None


def _amounts_are_close(first: Decimal, second: Decimal) -> bool:
    return abs(first - second) <= max(abs(first), abs(second)) * DUPLICATE_AMOUNT_TOLERANCE


def _are_duplicate_candidates(first: DuplicateCandidate, second: DuplicateCandidate) -> bool:
    first_client = _normalized_client_name(first.client_name)
    second_client = _normalized_client_name(second.client_name)
    if first_client is None or first_client != second_client:
        return False
    if first.amount is None or second.amount is None or not _amounts_are_close(first.amount, second.amount):
        return False
    if first.close_date is None or second.close_date is None:
        return False
    return abs((first.close_date - second.close_date).days) <= DUPLICATE_CLOSE_DATE_WINDOW_DAYS


def find_duplicate_candidates(records: Sequence[DuplicateCandidate]) -> list[DuplicateFlag]:
    """Flag pairs with matching normalized client, close amount, and close date.

    Source rows are deliberately never modified or merged.
    """
    flags: list[DuplicateFlag] = []
    for first_index, first in enumerate(records):
        for second in records[first_index + 1 :]:
            if _are_duplicate_candidates(first, second):
                flags.append(
                    DuplicateFlag(
                        record_id=first.record_id,
                        matching_record_id=second.record_id,
                        reasons=(
                            "normalized_client_match",
                            "amount_within_tolerance",
                            "close_date_within_window",
                        ),
                    )
                )
    return flags
