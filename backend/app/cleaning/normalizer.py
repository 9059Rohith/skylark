"""Date, amount, text, and sector normalizers."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

from rapidfuzz import fuzz, process

from app.cleaning.rules import SECTOR_ALIASES, SECTOR_FUZZY_THRESHOLD
from app.cleaning.schemas import NormalizedValue


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)
_CURRENCY_TOKEN = re.compile(r"(?:inr|rs\.?|rupees?|usd|\$|\u20b9)", re.IGNORECASE)
_MULTIPLIER = re.compile(r"\s*(cr|crore|l|lac|lakh|k)\s*$", re.IGNORECASE)
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?$")


def _original_value(value: object) -> str | None:
    return None if value is None else str(value)


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _invalid(value: object, reason: str, *, fallback: object = None) -> NormalizedValue:
    return NormalizedValue(
        value=fallback,
        original_value=_original_value(value),
        is_valid=False,
        reason=reason,
    )


def normalize_date(value: object) -> NormalizedValue[date]:
    """Parse supported date shapes without guessing outside their documented conventions."""
    if _is_missing(value):
        return _invalid(value, "missing_value")
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        parsed = None
        cleaned = value.strip()
        for date_format in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(cleaned, date_format).date()
                break
            except ValueError:
                continue
        if parsed is None:
            return _invalid(value, "invalid_date")
    else:
        return _invalid(value, "invalid_date")

    return NormalizedValue(
        value=parsed,
        original_value=_original_value(value),
        is_valid=True,
    )


def normalize_currency(
    value: object, usd_to_inr_rate: Decimal | None
) -> NormalizedValue[Decimal]:
    """Convert supported INR and USD amounts to INR base units using ``Decimal``."""
    if _is_missing(value):
        return _invalid(value, "missing_value")
    if isinstance(value, bool):
        return _invalid(value, "invalid_currency")

    cleaned = str(value).strip()
    is_usd = "$" in cleaned or bool(re.search(r"\busd\b", cleaned, re.IGNORECASE))
    without_currency = _CURRENCY_TOKEN.sub("", cleaned).strip()
    multiplier_match = _MULTIPLIER.search(without_currency)
    multiplier = Decimal("1")
    if multiplier_match:
        multiplier = {
            "k": Decimal("1000"),
            "l": Decimal("100000"),
            "lac": Decimal("100000"),
            "lakh": Decimal("100000"),
            "cr": Decimal("10000000"),
            "crore": Decimal("10000000"),
        }[multiplier_match.group(1).casefold()]
        without_currency = without_currency[: multiplier_match.start()].strip()

    number_text = without_currency.replace(",", "").replace(" ", "")
    if not _NUMBER.fullmatch(number_text):
        return _invalid(value, "invalid_currency")
    try:
        amount = Decimal(number_text) * multiplier
    except InvalidOperation:
        return _invalid(value, "invalid_currency")

    if is_usd:
        if usd_to_inr_rate is None:
            return _invalid(value, "usd_to_inr_rate_required")
        try:
            rate = Decimal(str(usd_to_inr_rate))
        except (InvalidOperation, ValueError):
            return _invalid(value, "invalid_exchange_rate")
        if rate <= 0:
            return _invalid(value, "invalid_exchange_rate")
        amount *= rate

    return NormalizedValue(
        value=amount,
        original_value=_original_value(value),
        is_valid=True,
    )


def _sector_key(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def normalize_sector(value: object) -> NormalizedValue[str]:
    """Resolve sector aliases first, then accept only conservative fuzzy matches."""
    if _is_missing(value):
        return _invalid(value, "missing_value", fallback="Unclassified")
    if not isinstance(value, str):
        return _invalid(value, "low_confidence_sector", fallback="Unclassified")

    key = _sector_key(value)
    if key in SECTOR_ALIASES:
        return NormalizedValue(
            value=SECTOR_ALIASES[key],
            original_value=value,
            is_valid=True,
            confidence=100.0,
        )

    match = process.extractOne(key, SECTOR_ALIASES.keys(), scorer=fuzz.ratio)
    if match is not None:
        matching_key, score, _ = match
        if score >= SECTOR_FUZZY_THRESHOLD:
            return NormalizedValue(
                value=SECTOR_ALIASES[matching_key],
                original_value=value,
                is_valid=True,
                confidence=float(score),
            )

    return _invalid(value, "low_confidence_sector", fallback="Unclassified")
