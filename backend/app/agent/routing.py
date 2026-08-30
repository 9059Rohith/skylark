"""Deterministic supported-intent routing and time-scope resolution."""

from calendar import monthrange
from datetime import date, datetime
from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict

from app.cleaning.rules import SECTOR_ALIASES


class Intent(StrEnum):
    PIPELINE_HEALTH = "pipeline_health"
    WON_WITHOUT_WORK_ORDERS = "won_without_work_orders"
    WORK_ORDER_COMPLETION = "work_order_completion"
    DATA_QUALITY = "data_quality"
    LEADERSHIP_UPDATE = "leadership_update"


class Period(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date
    label: str


class IntentDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: Intent
    period: Period | None = None
    sector: str | None = None
    breakdown_by_sector: bool = False
    clarification_question: str | None = None
    pending_clarification: dict[str, object] | None = None


def resolve_quarter(
    message: str, *, now: datetime, fiscal_year_start_month: int = 1
) -> Period | None:
    """Resolve `this quarter` against an injected clock and fiscal start month."""
    if "this quarter" not in message.casefold() and "current quarter" not in message.casefold():
        return None
    offset = (now.month - fiscal_year_start_month) % 12
    quarter = offset // 3 + 1
    fiscal_start_year = (
        now.year if now.month >= fiscal_year_start_month else now.year - 1
    )
    start_month_index = (fiscal_year_start_month - 1) + (quarter - 1) * 3
    start_year = fiscal_start_year + start_month_index // 12
    start_month = start_month_index % 12 + 1
    end_month_index = start_month + 2
    end_year = start_year + (end_month_index - 1) // 12
    end_month = (end_month_index - 1) % 12 + 1
    fiscal_year = fiscal_start_year if fiscal_year_start_month != 1 else now.year
    return Period(
        start=date(start_year, start_month, 1),
        end=date(end_year, end_month, monthrange(end_year, end_month)[1]),
        label=f"FY{fiscal_year} Q{quarter}"
        if fiscal_year_start_month != 1
        else f"{now.year} Q{quarter}",
    )


def resolve_period(
    message: str, *, now: datetime, fiscal_year_start_month: int = 1
) -> Period | None:
    """Resolve the supported relative calendar/fiscal periods deterministically."""
    lowered = message.casefold()
    if "this month" in lowered or "current month" in lowered:
        return Period(
            start=date(now.year, now.month, 1),
            end=date(now.year, now.month, monthrange(now.year, now.month)[1]),
            label=now.strftime("%B %Y"),
        )
    return resolve_quarter(
        message, now=now, fiscal_year_start_month=fiscal_year_start_month
    )


def _mentioned_sectors(message: str) -> list[str]:
    lowered = re.sub(r"[^a-z0-9]+", " ", message.casefold()).strip()
    found: list[str] = []
    for alias, canonical in sorted(SECTOR_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", lowered) and canonical not in found:
            found.append(canonical)
    return found


def _is_explicit_full_board_approval(message: str) -> bool:
    """Accept deliberate consent while rejecting negation and substring collisions."""
    normalized = re.sub(r"[^a-z0-9]+", " ", message.casefold()).strip()
    if re.search(r"\b(?:no|not|never|dont|cancel|stop)\b", normalized) or any(
        phrase in normalized for phrase in ("do not", "don t")
    ):
        return False
    if re.match(r"^(?:yes|yep|yeah|affirmative|absolutely)\b", normalized):
        return True
    if normalized in {
        "approve",
        "approved",
        "full board",
        "full deals board",
        "all deals",
        "whole deals board",
        "go ahead",
        "okay",
        "ok",
        "proceed",
        "sure",
    }:
        return True
    return bool(
        re.fullmatch(
            r"(?:please )?(?:use|report across|check|review) "
            r"(?:the )?(?:full|whole) (?:deals )?board(?: instead)?",
            normalized,
        )
    )


def _asks_for_missing_work_orders(message: str) -> bool:
    """Recognize common founder wording for the won-deal execution gap."""
    normalized = re.sub(r"[^a-z0-9]+", " ", message.casefold()).strip()
    if not re.search(r"\bwork orders?\b", normalized):
        return False
    return any(
        re.search(pattern, normalized)
        for pattern in (
            r"\b(?:no|without|missing)\b.*\bwork orders?\b",
            r"\b(?:do not|don t|dont)\s+(?:yet\s+)?have\b.*\bwork orders?\b",
            r"\black(?:s|ing)?\b.*\bwork orders?\b",
        )
    )


def parse_intent(
    message: str,
    *,
    prior_intent: Intent | str | None = None,
    prior_period: Period | dict[str, object] | None = None,
    pending_clarification: dict[str, object] | None = None,
    now: datetime | None = None,
    fiscal_year_start_month: int = 1,
) -> IntentDecision:
    """Route the five supported archetypes and contextual sector follow-ups."""
    lowered = message.casefold()
    follow_up = "sector" in lowered and any(
        phrase in lowered for phrase in ("break", "by sector", "sector split")
    )
    mentioned_sectors = _mentioned_sectors(message)
    pending_kind = (
        str(pending_clarification.get("kind")) if pending_clarification else None
    )
    pending_options = (
        [str(option) for option in pending_clarification.get("options", [])]
        if pending_clarification
        else []
    )
    pending_intent = (
        str(pending_clarification.get("intent"))
        if pending_clarification and pending_clarification.get("intent")
        else None
    )
    full_board_quality_resolution = (
        pending_kind == "data_quality_full_board"
        and _is_explicit_full_board_approval(message)
    )
    sector_resolution = (
        pending_kind == "sector"
        and len(mentioned_sectors) == 1
        and mentioned_sectors[0] in pending_options
    )
    recognized = False
    if full_board_quality_resolution and (pending_intent or prior_intent) is not None:
        intent = Intent(pending_intent or prior_intent)
        recognized = True
    elif sector_resolution and (pending_intent or prior_intent) is not None:
        intent = Intent(pending_intent or prior_intent)
        recognized = True
    elif follow_up and prior_intent is not None:
        intent = Intent(prior_intent)
        recognized = True
    elif "leadership" in lowered or "weekly update" in lowered:
        intent = Intent.LEADERSHIP_UPDATE
        recognized = True
    elif _asks_for_missing_work_orders(message):
        intent = Intent.WON_WITHOUT_WORK_ORDERS
        recognized = True
    elif "work order" in lowered and any(
        word in lowered for word in ("completion", "complete", "turnaround", "duration")
    ):
        intent = Intent.WORK_ORDER_COMPLETION
        recognized = True
    elif any(word in lowered for word in ("missing", "quality", "invalid", "duplicate")):
        intent = Intent.DATA_QUALITY
        recognized = True
    elif pending_kind in {"sector", "data_quality_full_board"} and pending_intent:
        intent = Intent(pending_intent)
        recognized = True
    else:
        intent = Intent.PIPELINE_HEALTH
        recognized = any(word in lowered for word in ("pipeline", "deal", "revenue"))

    sectors = mentioned_sectors
    contextual_period = (
        pending_clarification.get("period")
        if pending_clarification and pending_clarification.get("period")
        else prior_period
    )
    period = (
        Period.model_validate(contextual_period)
        if (follow_up or sector_resolution) and contextual_period
        else None
    )
    if period is None and now is not None and not full_board_quality_resolution:
        period = resolve_period(
            message, now=now, fiscal_year_start_month=fiscal_year_start_month
        )
    clarification = None
    pending: dict[str, object] | None = None
    if full_board_quality_resolution:
        period = None
    elif len(sectors) > 1:
        clarification = f"Which sector should I use: {' or '.join(sectors)}?"
        pending = {
            "kind": "sector",
            "options": sectors,
            "intent": intent.value,
            "period": period.model_dump(mode="json") if period else None,
        }
    elif pending_kind == "sector" and not sector_resolution:
        clarification = f"Which sector should I use: {' or '.join(pending_options)}?"
        pending = pending_clarification
    elif pending_kind == "data_quality_full_board":
        clarification = (
            "Rows missing close dates cannot be assigned to a quarter or month. "
            "Should I report across the full Deals board instead?"
        )
        pending = pending_clarification
    elif intent == Intent.DATA_QUALITY and period is not None:
        clarification = (
            "Rows missing close dates cannot be assigned to a quarter or month. "
            "Should I report across the full Deals board instead?"
        )
        pending = {
            "kind": "data_quality_full_board",
            "options": ["full Deals board"],
            "intent": intent.value,
            "period": period.model_dump(mode="json"),
        }
    elif not recognized:
        clarification = (
            "Which view do you need: pipeline health, won deals without work orders, "
            "work-order completion, data quality, or a leadership update?"
        )
        pending = {"kind": "intent", "options": [intent.value]}

    return IntentDecision(
        intent=intent,
        period=period,
        sector=sectors[0] if len(sectors) == 1 else None,
        breakdown_by_sector=follow_up,
        clarification_question=clarification,
        pending_clarification=pending,
    )
