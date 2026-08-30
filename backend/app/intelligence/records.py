"""Small record access helpers for mappings and normalized monday items."""

from collections.abc import Mapping
import re
from typing import Any

from app.monday.schemas import MondayItem


Record = Mapping[str, Any] | MondayItem


def normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def record_value(record: Record, *aliases: str) -> object:
    if isinstance(record, MondayItem):
        source: dict[str, Any] = {"id": record.id, "name": record.name, **record.values}
    else:
        source = dict(record)
    indexed = {normalized_key(key): value for key, value in source.items()}
    for alias in aliases:
        key = normalized_key(alias)
        if key in indexed:
            return indexed[key]
    return None


def text_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
