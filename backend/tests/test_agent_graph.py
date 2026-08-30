import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.agent.graph import AgentDependencies, AgentRunner, build_graph, run_agent
from app.config import Settings
from app.monday import (
    BoardItemsResult,
    BoardSchema,
    ColumnSchema,
    MondayAPIError,
    MondayItem,
)


DEAL_SCHEMA = BoardSchema(
    board_id="101",
    name="Deals",
    columns=(
        ColumnSchema(id="color7", title="Deal Stage", type="status"),
        ColumnSchema(id="numbers9", title="Contract Value", type="numbers"),
        ColumnSchema(id="text4", title="Customer Name", type="text"),
        ColumnSchema(id="dropdown2", title="Industry / Vertical", type="dropdown"),
        ColumnSchema(id="date11", title="Expected Close", type="date"),
    ),
)
WORK_ORDER_SCHEMA = BoardSchema(
    board_id="202",
    name="Work Orders",
    columns=(
        ColumnSchema(id="connect3", title="Linked Deal", type="board_relation"),
        ColumnSchema(id="date2", title="Kickoff Date", type="date"),
        ColumnSchema(id="date8", title="Completed Date", type="date"),
        ColumnSchema(id="client2", title="Customer", type="text"),
    ),
)


class FakeMonday:
    def __init__(self) -> None:
        self.active_fetches = 0
        self.max_active_fetches = 0

    async def get_board_schema(self, board_id: str) -> BoardSchema:
        return DEAL_SCHEMA if board_id == "101" else WORK_ORDER_SCHEMA

    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        self.active_fetches += 1
        self.max_active_fetches = max(self.max_active_fetches, self.active_fetches)
        await asyncio.sleep(0)
        self.active_fetches -= 1
        if board_id == "101":
            items = (
                MondayItem(
                    id="d-1",
                    name="Acme expansion",
                    values={
                        "color7": "Won",
                        "numbers9": "INR 10,00,000",
                        "text4": "Acme",
                        "dropdown2": "technology",
                        "date11": "2026-08-10",
                    },
                ),
                MondayItem(
                    id="d-2",
                    name="Beta rollout",
                    values={
                        "color7": "Proposal",
                        "numbers9": "2 Cr",
                        "text4": "Beta",
                        "dropdown2": "energy",
                        "date11": "2026-08-20",
                    },
                ),
            )
        else:
            items = (
                MondayItem(
                    id="wo-1",
                    name="Acme delivery",
                    values={
                        "connect3": ["d-1"],
                        "date2": "2026-08-11",
                        "date8": "2026-08-21",
                        "client2": "Acme",
                    },
                ),
            )
        return BoardItemsResult(board_id=board_id, items=items)

    async def search_items(self, board_id: str, filters: Any) -> BoardItemsResult:
        return await self.get_board_items(board_id)


class MissingScopeDateMonday(FakeMonday):
    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        result = await super().get_board_items(board_id)
        if board_id != "101":
            return result
        return result.model_copy(
            update={
                "items": (
                    *result.items,
                    MondayItem(
                        id="d-3",
                        name="Undated opportunity",
                        values={
                            "color7": "Qualified",
                            "numbers9": "INR 5,00,000",
                            "text4": "Gamma",
                            "dropdown2": "retail",
                            "date11": "",
                        },
                    ),
                )
            }
        )


class FakeClaude:
    configured = True

    def __init__(self) -> None:
        self.intent_calls = 0
        self.synthesis_calls = 0
        self.synthesis_payload: dict[str, Any] | None = None

    async def parse_intent(self, message: str, context: dict[str, Any]) -> None:
        self.intent_calls += 1
        return None

    async def stream_synthesis(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        self.synthesis_calls += 1
        self.synthesis_payload = payload
        yield "Pipeline "
        yield "is visible."


def settings() -> Settings:
    return Settings(
        deals_board_id="101",
        work_orders_board_id="202",
        anthropic_api_key=None,
        deterministic_synthesis_fallback=True,
        fiscal_year_start_month=4,
        app_timezone="Asia/Kolkata",
    )


def dependencies(monday: FakeMonday, claude: FakeClaude | None = None) -> AgentDependencies:
    return AgentDependencies(
        monday=monday,
        settings=settings(),
        claude=claude,
        clock=lambda: datetime(2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    )


@pytest.mark.asyncio
async def test_graph_runs_required_nodes_in_order_and_maps_live_column_titles() -> None:
    """Using source IDs as semantic names empties otherwise valid metrics."""
    monday = FakeMonday()
    graph = build_graph(dependencies(monday))

    result = await graph.ainvoke(
        {"message": "How healthy is our pipeline this quarter?", "session_id": "s-1"},
        config={"configurable": {"thread_id": "s-1"}},
    )

    assert result["node_trace"] == [
        "parse_intent",
        "plan_data_needs",
        "fetch_from_monday",
        "clean_and_normalize",
        "analyze",
        "synthesize_answer",
        "format_response",
    ]
    assert result["analysis"]["metrics"]["total_pipeline_value_inr"] == "21000000"
    assert result["sources"] == [
        {"board_id": "101", "board_name": "Deals", "item_count": 2}
    ]


@pytest.mark.asyncio
async def test_graph_fetches_required_boards_concurrently() -> None:
    """Sequential cross-board reads add avoidable monday latency."""
    monday = FakeMonday()
    graph = build_graph(dependencies(monday))

    await graph.ainvoke(
        {"message": "Which won deals have no work orders?", "session_id": "s-2"},
        config={"configurable": {"thread_id": "s-2"}},
    )

    assert monday.max_active_fetches == 2


@pytest.mark.asyncio
async def test_checkpointer_preserves_intent_for_sector_follow_up() -> None:
    """A new invocation with the same thread must retain conversational scope."""
    runner = AgentRunner(dependencies(FakeMonday()))

    await runner.run_agent("How healthy is our pipeline this quarter?", "thread-7")
    follow_up = await runner.run_agent("Break that down by sector", "thread-7")

    assert follow_up["intent"] == "pipeline_health"
    assert follow_up["breakdown_by_sector"] is True
    assert set(follow_up["analysis"]["metrics"]["sectors"]) == {"Energy", "Technology"}


@pytest.mark.asyncio
async def test_public_run_agent_interface_reuses_initialized_checkpointed_runner() -> None:
    """The two-argument public interface must preserve its session checkpoint."""
    await run_agent(
        "How healthy is our pipeline this quarter?",
        "public-thread-1",
        dependencies=dependencies(FakeMonday()),
    )

    follow_up = await run_agent("Break that down by sector", "public-thread-1")

    assert follow_up["intent"] == "pipeline_health"
    assert follow_up["breakdown_by_sector"] is True


@pytest.mark.asyncio
async def test_configured_claude_is_used_by_reasoning_and_synthesis_nodes() -> None:
    """Silently bypassing a configured Claude client violates the reasoning contract."""
    claude = FakeClaude()
    runner = AgentRunner(dependencies(FakeMonday(), claude))

    result = await runner.run_agent("How healthy is our pipeline?", "claude-1")

    assert claude.intent_calls == 1
    assert claude.synthesis_calls == 1
    assert result["answer"] == "Pipeline is visible."
    assert set(claude.synthesis_payload or {}) == {
        "intent",
        "period",
        "sector",
        "metrics",
        "sources",
        "caveats",
    }


@pytest.mark.asyncio
async def test_runner_streams_real_synthesis_deltas_from_langgraph_custom_mode() -> None:
    """Buffering Claude output until graph completion defeats token streaming."""
    runner = AgentRunner(dependencies(FakeMonday(), FakeClaude()))

    events = [
        event
        async for event in runner.stream_agent(
            "How healthy is our pipeline?", "stream-1", []
        )
    ]

    assert [event.token for event in events if event.event == "token"] == [
        "Pipeline ",
        "is visible.",
    ]
    source_event = next(event for event in events if event.event == "sources")
    assert source_event.sources[0].item_count == 2
    assert events[-1].event == "done"
    assert events[-1].intent == "pipeline_health"


@pytest.mark.asyncio
async def test_quarter_scope_exclusions_remain_in_quality_accounting() -> None:
    """Filtering before analysis must not make undated source rows disappear silently."""
    result = await AgentRunner(dependencies(MissingScopeDateMonday())).run_agent(
        "How healthy is our pipeline this quarter?", "scope-quality-1"
    )

    assert result["analysis"]["quality"]["total_rows"] == 3
    assert result["analysis"]["quality"]["exclusions"][
        "period_scope:missing_value"
    ] == 1


@pytest.mark.asyncio
async def test_leadership_quality_footnote_includes_period_scope_exclusions() -> None:
    """The draft footnote must use the same quality denominator as its headline."""
    result = await AgentRunner(dependencies(MissingScopeDateMonday())).run_agent(
        "Draft the leadership update for this quarter", "leadership-scope-1"
    )

    assert "1 of 3 pipeline rows were excluded" in result["leadership_update"][
        "quality_footnote"
    ]


@pytest.mark.asyncio
async def test_every_required_archetype_reaches_its_deterministic_analysis() -> None:
    """A route that exists but is not wired to its metric is not actually supported."""
    cases = [
        ("How healthy is our pipeline?", "total_pipeline_value_inr"),
        ("Which won deals have no work orders?", "missing_work_order_count"),
        ("What is average work order completion time?", "average_completion_days"),
        ("How many deals are missing close dates?", "missing_close_date_count"),
        ("Draft the weekly leadership update", "total_pipeline_value_inr"),
    ]
    for index, (message, metric) in enumerate(cases):
        result = await AgentRunner(dependencies(FakeMonday())).run_agent(
            message, f"archetype-{index}"
        )

        assert metric in result["analysis"]["metrics"]
        if "leadership" in message.casefold():
            assert result["leadership_update"]["markdown"].startswith(
                "# Leadership update (draft)"
            )


@pytest.mark.asyncio
async def test_ambiguous_sector_stops_at_single_clarification_node() -> None:
    """Ambiguous scope must not query boards or manufacture an answer."""
    monday = FakeMonday()
    runner = AgentRunner(dependencies(monday))

    result = await runner.run_agent(
        "Show pipeline for healthcare or energy", "clarify-1"
    )

    assert result["node_trace"] == ["parse_intent", "clarify"]
    assert result["answer"] == "Which sector should I use: Healthcare or Energy?"
    assert monday.max_active_fetches == 0


@pytest.mark.asyncio
async def test_streamed_clarification_contains_one_visible_question() -> None:
    """A clarification stored only in graph state never reaches an SSE chat client."""
    runner = AgentRunner(dependencies(FakeMonday()))

    events = [
        event
        async for event in runner.stream_agent(
            "Show pipeline for healthcare or energy", "clarify-stream-1", []
        )
    ]

    assert [event.token for event in events if event.event == "token"] == [
        "Which sector should I use: Healthcare or Energy?"
    ]


@pytest.mark.asyncio
async def test_partial_board_auth_failure_keeps_sources_and_clean_caveat() -> None:
    """One inaccessible board must not erase usable data or expose transport details."""

    class PartialMonday(FakeMonday):
        async def get_board_schema(self, board_id: str) -> BoardSchema:
            if board_id == "202":
                raise MondayAPIError(
                    "Authorization: bearer-secret-value",
                    classification="authentication",
                    retryable=False,
                )
            return await super().get_board_schema(board_id)

    events = [
        event
        async for event in AgentRunner(dependencies(PartialMonday())).stream_agent(
            "Which won deals have no work orders?", "partial-1", []
        )
    ]

    sources = next(event for event in events if event.event == "sources")
    caveats = next(event for event in events if event.event == "caveats")
    assert [source.board_name for source in sources.sources] == ["Deals", "Work Orders"]
    assert sources.sources[1].item_count == 0
    assert sources.sources[1].partial is True
    assert any("authentication failed" in caveat for caveat in caveats.caveats)
    assert "bearer-secret-value" not in " ".join(caveats.caveats)
    assert events[-1].event == "done"


@pytest.mark.asyncio
async def test_total_rate_limit_failure_is_one_clean_error_event() -> None:
    """Exhausted upstream rate limits must not leak exceptions or stack traces."""

    class RateLimitedMonday(FakeMonday):
        async def get_board_schema(self, board_id: str) -> BoardSchema:
            raise MondayAPIError(
                "HTTP 429 internal response", classification="rate_limit", retryable=True
            )

    events = [
        event
        async for event in AgentRunner(dependencies(RateLimitedMonday())).stream_agent(
            "Which won deals have no work orders?", "rate-1", []
        )
    ]

    assert events[-1].event == "error"
    assert events[-1].code == "data_source_unavailable"
    assert "rate-limited" in events[-1].message
    assert "HTTP 429" not in events[-1].message
