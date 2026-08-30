"""Normalization helpers shared by GraphQL and hosted-MCP client adapters."""

import json
from typing import Any

from app.monday.schemas import ColumnSchema


def _decoded_value(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_labels(value: object) -> list[str]:
    text = _clean_text(value)
    return [] if text is None else [part.strip() for part in text.split(",") if part.strip()]


def _relation_ids(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    linked_values = (
        value.get("linkedPulseIds")
        or value.get("linkedItemIds")
        or value.get("linked_item_ids")
        or []
    )
    if not isinstance(linked_values, list):
        return []
    ids: list[str] = []
    for linked_value in linked_values:
        if isinstance(linked_value, dict):
            linked_id = (
                linked_value.get("linkedPulseId")
                or linked_value.get("linkedItemId")
                or linked_value.get("id")
            )
        else:
            linked_id = linked_value
        normalized_id = _clean_text(linked_id)
        if normalized_id is not None:
            ids.append(normalized_id)
    return ids


def normalize_column_value(raw: dict[str, Any], schema: ColumnSchema | None = None) -> object:
    """Reduce monday column variants to scalars/lists before business cleaning."""
    column_type = str(raw.get("type") or (schema.type if schema else "")).casefold()
    text = _clean_text(raw.get("text"))
    decoded = _decoded_value(raw.get("value"))

    if column_type in {"status", "color"}:
        if text is not None:
            return text
        if isinstance(decoded, dict) and schema is not None:
            index = decoded.get("index")
            labels = schema.settings.get("labels", {})
            return labels.get(str(index)) or labels.get(index)
        return None

    if column_type == "date":
        if isinstance(decoded, dict):
            return _clean_text(decoded.get("date"))
        return text or _clean_text(decoded)

    if column_type in {"numbers", "numeric"}:
        return text or _clean_text(decoded)

    if column_type in {"text", "long_text", "email", "phone"}:
        return text or _clean_text(decoded)

    if column_type == "dropdown":
        labels = _split_labels(text)
        return labels[0] if len(labels) == 1 else labels

    if column_type in {"board_relation", "dependency"}:
        return _relation_ids(decoded)

    if column_type == "mirror":
        display = decoded.get("display_value") if isinstance(decoded, dict) else None
        return _split_labels(text or display)

    if text is not None:
        return text
    if isinstance(decoded, (str, int, float, bool, list, dict)):
        return decoded
    return None
