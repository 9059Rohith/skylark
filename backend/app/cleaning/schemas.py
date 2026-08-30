"""Typed models shared by the data-cleaning layer."""

from datetime import date
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


NormalizedType = TypeVar("NormalizedType")


class NormalizedValue(BaseModel, Generic[NormalizedType]):
    """A normalized value together with the uncertainty introduced by cleaning."""

    model_config = ConfigDict(frozen=True)

    value: NormalizedType | None
    original_value: str | None
    is_valid: bool
    reason: str | None = None
    confidence: float | None = None


class DuplicateCandidate(BaseModel):
    """The normalized fields required to flag, but never merge, duplicate-ish rows."""

    model_config = ConfigDict(frozen=True)

    record_id: str
    client_name: str | None
    amount: Decimal | None
    close_date: date | None


class DuplicateFlag(BaseModel):
    """Evidence that two source rows are sufficiently similar to review."""

    model_config = ConfigDict(frozen=True)

    record_id: str
    matching_record_id: str
    reasons: tuple[str, ...] = Field(min_length=1)
