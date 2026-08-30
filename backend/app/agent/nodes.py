"""Node implementations for the hand-rolled Skylark Signal graph."""

import asyncio
from collections import Counter
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
import re
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from pydantic_core import to_jsonable_python

from app.agent.routing import Intent, parse_intent
from app.agent.state import AgentContext, AgentState
from app.cleaning import normalize_date, normalize_sector
from app.cleaning.quality_report import DataQualityReport
from app.intelligence import (
    AnalysisResult,
    average_work_order_completion_time,
    missing_close_date_quality,
    pipeline_by_sector,
    pipeline_health,
    won_deals_without_work_orders,
)
from app.leadership import build_leadership_update
from app.monday import BoardItemsResult, BoardSchema, MondayAPIError


DEAL_TITLE_ALIASES = {
    "client": {"client", "client name", "customer", "customer name", "account"},
    "stage": {"stage", "deal stage", "pipeline stage", "status"},
    "amount": {"amount", "deal value", "contract value", "pipeline value", "estimated value"},
    "sector": {"sector", "industry", "vertical", "industry vertical"},
    "close_date": {"close date", "expected close", "expected close date", "closed date"},
    "last_reached_stage": {"last reached stage", "last stage before loss"},
    "stage_history": {"stage history", "stage history values"},
}
WORK_ORDER_TITLE_ALIASES = {
    "deal_id": {"deal id", "linked deal", "linked deal id", "deal relation"},
    "client": {"client", "client name", "customer", "customer name"},
    "start_date": {"start date", "started date", "kickoff", "kickoff date", "created date"},
    "completion_date": {"completion date", "completed date", "completed", "end date"},
    "status": {"status", "work order status"},
    "sector": {"sector", "industry", "vertical", "industry vertical"},
}


class AgentServiceError(RuntimeError):
    """A clean, classified graph failure safe to expose through SSE."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "agent_error",
        sources: list[dict[str, Any]] | None = None,
        caveats: list[str] | None = None,
        quality: DataQualityReport | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.sources = sources or []
        self.caveats = caveats or []
        self.quality = quality


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def map_live_columns(
    schema: BoardSchema, result: BoardItemsResult, *, board_kind: str
) -> list[dict[str, Any]]:
    """Map opaque monday column IDs through normalized live schema titles."""
    aliases = DEAL_TITLE_ALIASES if board_kind == "deals" else WORK_ORDER_TITLE_ALIASES
    semantic_by_id: dict[str, str] = {}
    for column in schema.columns:
        normalized = _normalized_title(column.title)
        semantic = next(
            (name for name, titles in aliases.items() if normalized in titles), None
        )
        if semantic is not None and semantic not in semantic_by_id.values():
            semantic_by_id[column.id] = semantic
    records: list[dict[str, Any]] = []
    for item in result.items:
        record: dict[str, Any] = {"id": item.id, "name": item.name}
        for column_id, semantic in semantic_by_id.items():
            if column_id in item.values:
                record[semantic] = item.values[column_id]
        records.append(record)
    return records


def _trace(state: AgentState, name: str) -> list[str]:
    return [*state.get("node_trace", []), name]


def _public_monday_error(board_name: str, error: MondayAPIError) -> str:
    if error.classification == "authentication":
        return f"{board_name} could not be read because monday.com authentication failed."
    if error.classification == "permission":
        return f"{board_name} could not be read because the monday.com token lacks access."
    if error.classification == "rate_limit":
        return f"{board_name} is temporarily unavailable because monday.com rate-limited the request."
    return f"{board_name} could not be read ({error.classification})."


def _safe_partial_caveat(caveat: str) -> str:
    lowered = caveat.casefold()
    if any(marker in lowered for marker in ("secret", "token", "bearer", "authorization")):
        return "monday.com returned partial board results; some rows may be missing."
    return caveat


def _quality_caveats(result: AnalysisResult) -> list[str]:
    quality = result.quality
    caveats: list[str] = []
    excluded = quality.total_rows - quality.included_rows
    if excluded:
        caveats.append(
            f"{excluded} of {quality.total_rows} rows were excluded from this metric; "
            f"reasons: {quality.exclusions}."
        )
    if quality.duplicate_records:
        caveats.append(
            f"{len(quality.duplicate_records)} duplicate-ish pair(s) were flagged but not merged."
        )
    return caveats


def _filter_period(
    records: list[dict[str, Any]], field: str, period: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    start = date.fromisoformat(str(period["start"]))
    end = date.fromisoformat(str(period["end"]))
    included = []
    exclusions: Counter[str] = Counter()
    for record in records:
        normalized = normalize_date(record.get(field))
        if normalized.is_valid and normalized.value is not None and start <= normalized.value <= end:
            included.append(record)
        elif not normalized.is_valid:
            exclusions[f"period_scope:{normalized.reason or 'invalid_date'}"] += 1
        else:
            exclusions["period_scope:outside_period"] += 1
    return included, dict(exclusions)


def _with_scope_quality(
    result: AnalysisResult, exclusions: Mapping[str, int]
) -> AnalysisResult:
    if not exclusions:
        return result
    combined = Counter(result.quality.exclusions)
    combined.update(exclusions)
    excluded_count = sum(exclusions.values())
    quality = DataQualityReport(
        total_rows=result.quality.total_rows + excluded_count,
        included_rows=result.quality.included_rows,
        exclusions=dict(combined),
        normalization_notes=[
            *result.quality.normalization_notes,
            "Rows outside or unassignable to the requested period remain in quality accounting.",
        ],
        duplicate_records=result.quality.duplicate_records,
    )
    return result.model_copy(update={"quality": quality})


def _direct_answer(state: AgentState) -> str:
    metrics = state.get("analysis", {}).get("metrics", {})
    intent = state.get("intent")
    if intent == Intent.PIPELINE_HEALTH:
        if "sectors" in metrics:
            direct = f"Pipeline is split across {len(metrics['sectors'])} normalized sector(s)."
        else:
            direct = (
                f"Total pipeline is INR {metrics.get('total_pipeline_value_inr', '0')} "
                f"across {metrics.get('deal_count', 0)} deal(s)."
            )
    elif intent == Intent.WON_WITHOUT_WORK_ORDERS:
        direct = f"{metrics.get('missing_work_order_count', 0)} won deal(s) have no matching work order."
    elif intent == Intent.WORK_ORDER_COMPLETION:
        direct = f"Average work-order completion time is {metrics.get('average_completion_days')} calendar days."
    elif intent == Intent.DATA_QUALITY:
        direct = f"{metrics.get('missing_close_date_count', 0)} deal(s) are missing close dates."
    else:
        direct = "The leadership update draft is ready for human review."
    return direct


def _material_caveat(state: AgentState) -> str:
    caveat = state.get("caveats", [])
    return (
        f"Material caveat: {caveat[0]}"
        if caveat
        else "Material caveat: no row-level caveat affected the aggregate."
    )


def _deterministic_context() -> str:
    return (
        "The result uses normalized live board fields. "
        "Source provenance and quality accounting remain attached to this answer."
    )


def _sentence_count(value: str) -> int:
    return len(re.findall(r"[.!?](?=\s|$)", value))


def _up_to_four_sentences(value: str) -> str:
    endings = list(re.finditer(r"[.!?](?=\s|$)", value))
    if len(endings) <= 4:
        return value
    return value[: endings[3].end()]


class GraphNodes:
    def __init__(self, dependencies: Any) -> None:
        self.dependencies = dependencies

    async def parse_intent(
        self, state: AgentState, runtime: Runtime[AgentContext]
    ) -> dict[str, Any]:
        message = runtime.context["message"]
        now = self.dependencies.clock()
        decision = parse_intent(
            message,
            prior_intent=state.get("intent"),
            prior_period=state.get("period"),
            pending_clarification=state.get("pending_clarification"),
            now=now,
            fiscal_year_start_month=self.dependencies.settings.fiscal_year_start_month,
        )
        pending_kind = (
            decision.pending_clarification.get("kind")
            if decision.pending_clarification
            else None
        )
        if (
            self.dependencies.llm is not None
            and decision.clarification_question
            and pending_kind == "intent"
        ):
            try:
                suggestion = await self.dependencies.llm.parse_intent(
                    message,
                    {"intent": state.get("intent"), "period": state.get("period")},
                )
            except Exception:
                suggestion = None
            if isinstance(suggestion, Mapping) and suggestion.get("intent"):
                try:
                    decision = decision.model_copy(
                        update={
                            "intent": Intent(str(suggestion["intent"])),
                            "clarification_question": None,
                            "pending_clarification": None,
                        }
                    )
                except ValueError:
                    pass
        return {
            "intent": decision.intent.value,
            "period": decision.period.model_dump(mode="json") if decision.period else None,
            "sector": decision.sector,
            "breakdown_by_sector": decision.breakdown_by_sector,
            "clarification_question": decision.clarification_question,
            "pending_clarification": decision.pending_clarification,
            "required_boards": [],
            "fetched": {},
            "records": {},
            "scope_exclusions": {},
            "sources": [],
            "caveats": [],
            "analysis": {},
            "answer": "",
            "leadership_update": None,
            "node_trace": ["parse_intent"],
        }

    async def clarify(self, state: AgentState) -> dict[str, Any]:
        get_stream_writer()(
            {"event": "token", "token": state["clarification_question"]}
        )
        return {
            "answer": state["clarification_question"],
            "node_trace": _trace(state, "clarify"),
        }

    async def plan_data_needs(self, state: AgentState) -> dict[str, Any]:
        intent = Intent(state["intent"])
        boards = {
            Intent.PIPELINE_HEALTH: ["deals"],
            Intent.WON_WITHOUT_WORK_ORDERS: ["deals", "work_orders"],
            Intent.WORK_ORDER_COMPLETION: ["work_orders"],
            Intent.DATA_QUALITY: ["deals"],
            Intent.LEADERSHIP_UPDATE: ["deals", "work_orders"],
        }[intent]
        return {"required_boards": boards, "node_trace": _trace(state, "plan_data_needs")}

    async def fetch_from_monday(self, state: AgentState) -> dict[str, Any]:
        board_ids = {
            "deals": self.dependencies.settings.deals_board_id,
            "work_orders": self.dependencies.settings.work_orders_board_id,
        }

        async def fetch(kind: str) -> tuple[str, BoardSchema, BoardItemsResult]:
            board_id = board_ids[kind]
            if not board_id:
                raise AgentServiceError(f"The {kind} board ID is not configured.", code="configuration")
            schema = await self.dependencies.monday.get_board_schema(board_id)
            items = await self.dependencies.monday.get_board_items(board_id)
            return kind, schema, items

        required = state["required_boards"]
        outcomes = await asyncio.gather(*(fetch(kind) for kind in required), return_exceptions=True)
        fetched: dict[str, Any] = {}
        sources: list[dict[str, Any]] = []
        caveats: list[str] = []
        for kind, outcome in zip(required, outcomes, strict=True):
            if isinstance(outcome, MondayAPIError):
                board_name = kind.replace("_", " ").title()
                public_error = _public_monday_error(board_name, outcome)
                caveats.append(public_error)
                sources.append(
                    {
                        "board_id": board_ids[kind],
                        "board_name": board_name,
                        "item_count": 0,
                        "partial": True,
                        "error": public_error,
                    }
                )
                continue
            if isinstance(outcome, Exception):
                if isinstance(outcome, AgentServiceError):
                    raise outcome
                board_name = kind.replace("_", " ").title()
                public_error = f"{board_name} could not be read."
                caveats.append(public_error)
                sources.append(
                    {
                        "board_id": board_ids[kind],
                        "board_name": board_name,
                        "item_count": 0,
                        "partial": True,
                        "error": public_error,
                    }
                )
                continue
            _, schema, items = outcome
            fetched[kind] = {
                "schema": schema.model_dump(mode="json"),
                "items": items.model_dump(mode="json"),
            }
            sources.append(
                {"board_id": schema.board_id, "board_name": schema.name, "item_count": len(items.items)}
            )
            if items.partial:
                sources[-1]["partial"] = True
                sources[-1]["error"] = "monday.com returned partial board results."
            caveats.extend(_safe_partial_caveat(caveat) for caveat in items.caveats)
        failed_required = len(fetched) != len(required)
        if failed_required and len(required) > 1:
            raise AgentServiceError(
                caveats[0] if caveats else "A required monday.com board could not be read.",
                code="required_source_unavailable",
                sources=sources,
                caveats=caveats,
            )
        if not fetched:
            raise AgentServiceError(
                caveats[0] if caveats else "No required monday.com board could be read.",
                code="data_source_unavailable",
                sources=sources,
                caveats=caveats,
            )
        return {
            "fetched": fetched,
            "sources": sources,
            "caveats": caveats,
            "node_trace": _trace(state, "fetch_from_monday"),
        }

    async def clean_and_normalize(self, state: AgentState) -> dict[str, Any]:
        records: dict[str, list[dict[str, Any]]] = {}
        scope_exclusions: dict[str, dict[str, int]] = {}
        for kind, payload in state["fetched"].items():
            schema = BoardSchema.model_validate(payload["schema"])
            items = BoardItemsResult.model_validate(payload["items"])
            records[kind] = map_live_columns(schema, items, board_kind=kind)
        period = state.get("period")
        intent = Intent(state["intent"])
        if (
            period
            and "deals" in records
            and intent
            in {
                Intent.PIPELINE_HEALTH,
                Intent.WON_WITHOUT_WORK_ORDERS,
                Intent.LEADERSHIP_UPDATE,
            }
        ):
            records["deals"], scope_exclusions["deals"] = _filter_period(
                records["deals"], "close_date", period
            )
        if (
            period
            and "work_orders" in records
            and intent == Intent.WORK_ORDER_COMPLETION
        ):
            records["work_orders"], scope_exclusions["work_orders"] = _filter_period(
                records["work_orders"], "completion_date", period
            )
        sector = state.get("sector")
        if sector and "deals" in records:
            records["deals"] = [
                record
                for record in records["deals"]
                if normalize_sector(record.get("sector")).value == sector
            ]
        return {
            "records": records,
            "scope_exclusions": scope_exclusions,
            "node_trace": _trace(state, "clean_and_normalize"),
        }

    async def analyze(self, state: AgentState) -> dict[str, Any]:
        intent = Intent(state["intent"])
        deals = state.get("records", {}).get("deals", [])
        work_orders = state.get("records", {}).get("work_orders", [])
        rate = (
            Decimal(self.dependencies.settings.usd_to_inr_rate)
            if self.dependencies.settings.usd_to_inr_rate
            else None
        )
        leadership = None
        if intent == Intent.PIPELINE_HEALTH and state.get("breakdown_by_sector"):
            result = pipeline_by_sector(deals, usd_to_inr_rate=rate)
        elif intent == Intent.PIPELINE_HEALTH:
            result = pipeline_health(deals, usd_to_inr_rate=rate)
        elif intent == Intent.WON_WITHOUT_WORK_ORDERS:
            result = won_deals_without_work_orders(deals, work_orders)
        elif intent == Intent.WORK_ORDER_COMPLETION:
            result = average_work_order_completion_time(work_orders)
        elif intent == Intent.DATA_QUALITY:
            result = missing_close_date_quality(deals)
        else:
            pipeline = pipeline_health(deals, usd_to_inr_rate=rate)
            sectors = pipeline_by_sector(deals, usd_to_inr_rate=rate)
            gaps = won_deals_without_work_orders(deals, work_orders)
            deal_scope_exclusions = state.get("scope_exclusions", {}).get("deals", {})
            pipeline = _with_scope_quality(
                pipeline, deal_scope_exclusions
            )
            sectors = _with_scope_quality(sectors, deal_scope_exclusions)
            gaps = _with_scope_quality(gaps, deal_scope_exclusions)
            result = pipeline
            leadership = build_leadership_update(
                pipeline, sectors, gaps, work_orders=work_orders
            )
        if intent != Intent.LEADERSHIP_UPDATE:
            scope_kind = (
                "work_orders" if intent == Intent.WORK_ORDER_COMPLETION else "deals"
            )
            result = _with_scope_quality(
                result, state.get("scope_exclusions", {}).get(scope_kind, {})
            )
        caveats = [*state.get("caveats", []), *_quality_caveats(result)]
        return {
            "analysis": to_jsonable_python(result.model_dump()),
            "leadership_update": (
                leadership.model_dump(mode="json") if leadership is not None else None
            ),
            "caveats": caveats,
            "node_trace": _trace(state, "analyze"),
        }

    async def synthesize_answer(self, state: AgentState) -> dict[str, Any]:
        payload = {
            "intent": state["intent"],
            "period": state.get("period"),
            "sector": state.get("sector"),
            "metrics": state.get("analysis", {}).get("metrics", {}),
            "sources": state.get("sources", []),
            "caveats": state.get("caveats", []),
        }
        writer = get_stream_writer()
        direct = _direct_answer(state)
        writer({"event": "token", "token": f"{direct} "})
        context_pieces: list[str] = []
        context_length = 0
        sentence_count = 0
        max_chars = self.dependencies.settings.llm_context_max_chars
        if self.dependencies.llm is not None:
            async for piece in self.dependencies.llm.stream_synthesis(payload):
                if any(character.isdigit() for character in piece):
                    break
                remaining = max_chars - context_length
                if remaining <= 0 or sentence_count >= 4:
                    break
                candidate = _up_to_four_sentences(piece[:remaining])
                allowed_sentences = 4 - sentence_count
                if _sentence_count(candidate) > allowed_sentences:
                    endings = list(re.finditer(r"[.!?](?=\s|$)", candidate))
                    candidate = candidate[: endings[allowed_sentences - 1].end()]
                if candidate:
                    writer({"event": "token", "token": candidate})
                    context_pieces.append(candidate)
                    context_length += len(candidate)
                    sentence_count += _sentence_count(candidate)
                if len(candidate) < len(piece) or sentence_count >= 4:
                    break
        elif self.dependencies.settings.deterministic_synthesis_fallback:
            fallback = _deterministic_context()
            writer({"event": "token", "token": fallback})
            context_pieces.append(fallback)
            sentence_count = 2
        else:
            raise AgentServiceError(
                "Claude is not configured and deterministic fallback is disabled.",
                code="configuration",
            )
        context = "".join(context_pieces).strip()
        if context and context[-1] not in ".!?" and sentence_count < 4:
            writer({"event": "token", "token": "."})
            context += "."
            sentence_count += 1
        filler_sentences = (
            "The result uses normalized live board fields.",
            "Source provenance and quality accounting remain attached to this answer.",
        )
        for filler in filler_sentences:
            if sentence_count >= 2:
                break
            separator = " " if context else ""
            writer({"event": "token", "token": f"{separator}{filler}"})
            context = f"{context}{separator}{filler}"
            sentence_count += 1
        material_caveat = _material_caveat(state)
        writer({"event": "token", "token": f" {material_caveat}"})
        return {
            "answer": f"{direct} {context} {material_caveat}",
            "node_trace": _trace(state, "synthesize_answer"),
        }

    async def format_response(self, state: AgentState) -> dict[str, Any]:
        return {"node_trace": _trace(state, "format_response")}
