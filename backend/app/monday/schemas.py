"""Internal, transport-independent monday.com board schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ColumnSchema(BaseModel):
    """The stable subset of monday column metadata needed by normalization."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    type: str
    settings: dict[str, Any] = Field(default_factory=dict)


class BoardSchema(BaseModel):
    """A board's column schema plus any non-fatal GraphQL caveats."""

    model_config = ConfigDict(frozen=True)

    board_id: str
    name: str
    columns: tuple[ColumnSchema, ...]
    caveats: tuple[str, ...] = ()


class MondayItem(BaseModel):
    """A monday item whose column envelopes have been reduced to internal values."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    values: dict[str, Any] = Field(default_factory=dict)


class BoardItemsResult(BaseModel):
    """All fetched items and explicit partial-result caveats."""

    model_config = ConfigDict(frozen=True)

    board_id: str
    items: tuple[MondayItem, ...]
    caveats: tuple[str, ...] = ()
    partial: bool = False


class SearchFilters(BaseModel):
    """Safe client-side filters over fully paginated, normalized board items."""

    model_config = ConfigDict(frozen=True)

    name_contains: str | None = None
    column_values: dict[str, Any] = Field(default_factory=dict)
