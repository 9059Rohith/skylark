import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.agent.graph import AgentDependencies, AgentRunner, build_graph, run_agent
from app.agent.llm import OpenAIService
from app.config import Settings
from app.monday import (
    BoardItemsResult,
    BoardSchema,
    ColumnSchema,
    MondayAPIError,
    MondayItem,
)


def sid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


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


class PriorMonthWorkOrderMonday(FakeMonday):
    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        result = await super().get_board_items(board_id)
        if board_id != "202":
            return result
        item = result.items[0].model_copy(
            update={
                "values": {
                    **result.items[0].values,
                    "date8": "2026-07-21",
                }
            }
        )
        return result.model_copy(update={"items": (item,)})


class PriorMonthDealMonday(FakeMonday):
    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        result = await super().get_board_items(board_id)
        if board_id != "101":
            return result
        prior = result.items[1].model_copy(
            update={"values": {**result.items[1].values, "date11": "2026-07-20"}}
        )
        return result.model_copy(update={"items": (result.items[0], prior)})


class PartialPagesMonday(FakeMonday):
    async def get_board_items(self, board_id: str) -> BoardItemsResult:
        result = await super().get_board_items(board_id)
        return result.model_copy(
            update={
                "partial": True,
                "caveats": ("Later page failed: bearer super-secret-token",),
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
        yield "Pipeline composition is concentrated. "
        yield "Execution attention remains important."


def settings() -> Settings:
    return Settings(
        MONDAY_DEALS_BOARD_ID="101",
        MONDAY_WORK_ORDERS_BOARD_ID="202",
        anthropic_api_key=None,
        deterministic_synthesis_fallback=True,
        fiscal_year_start_month=4,
        app_timezone="Asia/Kolkata",
    )


def dependencies(monday: FakeMonday, claude: FakeClaude | None = None) -> AgentDependencies:
    return AgentDependencies(
        monday=monday,
        settings=settings(),
        llm=claude,
        clock=lambda: datetime(2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    )


@pytest.mark.asyncio
async def test_graph_runs_required_nodes_in_order_and_maps_live_column_titles() -> None:
    """Using source IDs as semantic names empties otherwise valid metrics."""
    monday = FakeMonday()
    graph = build_graph(dependencies(monday))

    result = await graph.ainvoke(
        {},
        config={"configurable": {"thread_id": "s-1"}},
        context={
            "message": "How healthy is our pipeline this quarter?",
            "session_id": "s-1",
        },
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
        {},
        config={"configurable": {"thread_id": "s-2"}},
        context={
            "message": "Which won deals have no work orders?",
            "session_id": "s-2",
        },
    )

    assert monday.max_active_fetches == 2


@pytest.mark.asyncio
async def test_checkpointer_preserves_intent_for_sector_follow_up() -> None:
    """A new invocation with the same thread must retain conversational scope."""
    runner = AgentRunner(dependencies(FakeMonday()))

    await runner.run_agent("How healthy is our pipeline this quarter?", sid(7))
    follow_up = await runner.run_agent("Break that down by sector", sid(7))

    assert follow_up["intent"] == "pipeline_health"
    assert follow_up["breakdown_by_sector"] is True
    assert set(follow_up["analysis"]["metrics"]["sectors"]) == {"Energy", "Technology"}


@pytest.mark.asyncio
async def test_sector_clarification_direct_answer_reuses_pending_context() -> None:
    """A direct option answer must resolve the pending sector instead of losing intent."""
    monday = FakeMonday()
    runner = AgentRunner(dependencies(monday))
    await runner.run_agent(
        "Show pipeline for healthcare or energy", sid(8)
    )

    result = await runner.run_agent("Healthcare", sid(8))

    assert result["intent"] == "pipeline_health"
    assert result["sector"] == "Healthcare"
    assert result["clarification_question"] is None
    assert result["analysis"]["metrics"]["deal_count"] == 0
    assert monday.max_active_fetches == 1


@pytest.mark.asyncio
async def test_data_quality_period_clarification_accepts_full_board_answer() -> None:
    """A direct yes must reuse data-quality intent and discard the impossible period."""
    monday = FakeMonday()
    runner = AgentRunner(dependencies(monday))
    result = await runner.run_agent(
        "How many deals are missing close dates this month?", sid(9)
    )

    assert result["node_trace"] == ["parse_intent", "clarify"]
    assert result["answer"] == (
        "Rows missing close dates cannot be assigned to a quarter or month. "
        "Should I report across the full Deals board instead?"
    )
    assert monday.max_active_fetches == 0

    declined = await runner.run_agent("No, keep the original scope", sid(9))
    assert declined["node_trace"] == ["parse_intent", "clarify"]
    assert declined["pending_clarification"]["kind"] == "data_quality_full_board"
    assert monday.max_active_fetches == 0

    answered = await runner.run_agent("Yes, use the full board", sid(9))

    assert answered["intent"] == "data_quality"
    assert answered["period"] is None
    assert answered["clarification_question"] is None
    assert answered["analysis"]["metrics"]["missing_close_date_count"] == 0
    assert monday.max_active_fetches == 1


@pytest.mark.asyncio
async def test_data_quality_full_board_consent_rejects_negative_and_unrelated_replies() -> None:
    """Substring matches must never turn negation or 'Yesterday' into scope consent."""
    monday = FakeMonday()
    runner = AgentRunner(dependencies(monday))
    await runner.run_agent(
        "How many deals are missing close dates this month?", sid(38)
    )

    for reply in (
        "No, don't use the full board",
        "Do not proceed",
        "Yesterday was busy",
    ):
        result = await runner.run_agent(reply, sid(38))
        assert result["node_trace"] == ["parse_intent", "clarify"]
        assert result["pending_clarification"]["kind"] == "data_quality_full_board"
        assert monday.max_active_fetches == 0

    approved = await runner.run_agent("Use the full Deals board", sid(38))
    assert approved["intent"] == "data_quality"
    assert approved["period"] is None
    assert approved["clarification_question"] is None
    assert monday.max_active_fetches == 1


@pytest.mark.asyncio
async def test_cross_board_period_scopes_won_deals_but_keeps_all_work_order_evidence() -> None:
    """Filtering evidence work orders can falsely classify a won deal as unfulfilled."""
    result = await AgentRunner(dependencies(PriorMonthWorkOrderMonday())).run_agent(
        "Which won deals have no work orders this month?", sid(10)
    )

    assert result["analysis"]["metrics"]["missing_work_order_count"] == 0
    assert result["analysis"]["quality"]["total_rows"] == 3
    assert result["analysis"]["quality"]["included_rows"] == 2


@pytest.mark.asyncio
async def test_completion_period_scopes_work_orders_by_completion_date() -> None:
    """Completion-time questions must apply month scope to completion dates."""
    result = await AgentRunner(dependencies(PriorMonthWorkOrderMonday())).run_agent(
        "What is work order completion time this month?", sid(11)
    )

    assert result["analysis"]["metrics"]["completed_work_order_count"] == 0
    assert result["analysis"]["quality"]["exclusions"][
        "period_scope:outside_period"
    ] == 1


@pytest.mark.asyncio
async def test_pipeline_month_scope_filters_deals_by_close_date() -> None:
    """Pipeline periods are defined by deal close date, with exclusions traceable."""
    result = await AgentRunner(dependencies(PriorMonthDealMonday())).run_agent(
        "How healthy is the pipeline this month?", sid(36)
    )

    assert result["analysis"]["metrics"]["total_pipeline_value_inr"] == "1000000"
    assert result["analysis"]["quality"]["exclusions"][
        "period_scope:outside_period"
    ] == 1


@pytest.mark.asyncio
async def test_public_run_agent_interface_reuses_initialized_checkpointed_runner() -> None:
    """The two-argument public interface must preserve its session checkpoint."""
    await run_agent(
        "How healthy is our pipeline this quarter?",
        sid(12),
        dependencies=dependencies(FakeMonday()),
    )

    follow_up = await run_agent("Break that down by sector", sid(12))

    assert follow_up["intent"] == "pipeline_health"
    assert follow_up["breakdown_by_sector"] is True


@pytest.mark.asyncio
async def test_deterministic_routing_stays_authoritative_when_claude_is_configured() -> None:
    """Claude must not override a supported route already resolved deterministically."""
    claude = FakeClaude()
    runner = AgentRunner(dependencies(FakeMonday(), claude))

    result = await runner.run_agent("How healthy is our pipeline?", sid(13))

    assert claude.intent_calls == 0
    assert claude.synthesis_calls == 1
    assert result["answer"].startswith("Total pipeline is INR 21000000")
    assert "Pipeline composition is concentrated." in result["answer"]
    assert result["answer"].endswith(
        "Material caveat: no row-level caveat affected the aggregate."
    )
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
        async for event in runner.stream_agent("How healthy is our pipeline?", sid(14))
    ]

    streamed_answer = "".join(
        event.token for event in events if event.event == "token"
    )
    assert streamed_answer.startswith("Total pipeline is INR 21000000")
    assert streamed_answer.endswith(
        "Material caveat: no row-level caveat affected the aggregate."
    )
    source_event = next(event for event in events if event.event == "sources")
    assert source_event.sources[0].item_count == 2
    assert events[-1].event == "done"
    assert events[-1].intent == "pipeline_health"


@pytest.mark.asyncio
async def test_runner_emits_prefix_and_safe_claude_deltas_before_stream_completion() -> None:
    """The structural frame must not force Claude context to be buffered until completion."""

    class BlockingClaude(FakeClaude):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()
            self.completed = False

        async def stream_synthesis(self, payload: dict[str, Any]) -> AsyncIterator[str]:
            yield "Pipeline composition is concentrated. "
            await self.release.wait()
            yield "Execution attention remains important."
            self.completed = True

    claude = BlockingClaude()
    runner = AgentRunner(dependencies(FakeMonday(), claude))
    events: list[Any] = []
    first_token = asyncio.Event()

    async def collect() -> None:
        async for event in runner.stream_agent(
            "How healthy is our pipeline?", sid(37)
        ):
            events.append(event)
            if event.event == "token":
                first_token.set()

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(first_token.wait(), timeout=0.5)
        assert claude.completed is False
    finally:
        claude.release.set()
        await task

    tokens = [event.token for event in events if event.event == "token"]
    assert tokens[0].startswith("Total pipeline is INR 21000000")
    assert "Pipeline composition is concentrated. " in tokens
    assert "Execution attention remains important." in tokens
    assembled = "".join(tokens)
    assert assembled.index("Total pipeline") < assembled.index("Pipeline composition")
    assert assembled.index("Pipeline composition") < assembled.index("Material caveat:")


@pytest.mark.asyncio
async def test_claude_routing_is_used_only_for_unresolved_intent_and_errors_fall_back() -> None:
    """An LLM routing failure must preserve the deterministic clarification path."""

    class RoutingClaude(FakeClaude):
        async def parse_intent(self, message: str, context: dict[str, Any]) -> Any:
            self.intent_calls += 1
            return {"intent": "data_quality"}

    routed_claude = RoutingClaude()
    routed = await AgentRunner(dependencies(FakeMonday(), routed_claude)).run_agent(
        "How are things looking?", sid(17)
    )
    assert routed["intent"] == "data_quality"
    assert routed_claude.intent_calls == 1

    class FailingRoutingClaude(FakeClaude):
        async def parse_intent(self, message: str, context: dict[str, Any]) -> Any:
            raise RuntimeError("upstream prompt failure")

    fallback = await AgentRunner(
        dependencies(FakeMonday(), FailingRoutingClaude())
    ).run_agent("How are things looking?", sid(18))
    assert fallback["node_trace"] == ["parse_intent", "clarify"]


@pytest.mark.asyncio
async def test_unvalidated_claude_numbers_are_not_emitted() -> None:
    """Model-invented numbers must not escape the deterministic public frame."""

    class HallucinatingClaude(FakeClaude):
        async def stream_synthesis(self, payload: dict[str, Any]) -> AsyncIterator[str]:
            yield "There are 999 hidden deals. Only one sentence."

    runner = AgentRunner(dependencies(FakeMonday(), HallucinatingClaude()))
    events = [
        event
        async for event in runner.stream_agent(
            "How healthy is the pipeline?", sid(19)
        )
    ]
    streamed = "".join(event.token for event in events if event.event == "token")
    result = await runner.run_agent("How healthy is the pipeline?", sid(19))

    assert "999" not in streamed
    assert "999" not in result["answer"]
    assert result["answer"].startswith("Total pipeline is INR 21000000")
    assert result["answer"].endswith(
        "Material caveat: no row-level caveat affected the aggregate."
    )


@pytest.mark.asyncio
async def test_quarter_scope_exclusions_remain_in_quality_accounting() -> None:
    """Filtering before analysis must not make undated source rows disappear silently."""
    result = await AgentRunner(dependencies(MissingScopeDateMonday())).run_agent(
        "How healthy is our pipeline this quarter?", sid(15)
    )

    assert result["analysis"]["quality"]["total_rows"] == 3
    assert result["analysis"]["quality"]["exclusions"][
        "period_scope:missing_value"
    ] == 1


@pytest.mark.asyncio
async def test_leadership_quality_footnote_includes_period_scope_exclusions() -> None:
    """The draft footnote must use the same quality denominator as its headline."""
    result = await AgentRunner(dependencies(MissingScopeDateMonday())).run_agent(
        "Draft the leadership update for this quarter", sid(16)
    )

    assert "1 of 3 pipeline rows were excluded" in result["leadership_update"][
        "quality_footnote"
    ]
    assert result["leadership_update"]["quality"]["sector"]["total_rows"] == 3
    assert result["leadership_update"]["quality"]["gaps"]["total_rows"] == 4


@pytest.mark.asyncio
async def test_caveats_event_always_carries_answer_quality_even_without_prose_caveats() -> None:
    """A clean dataset still needs its complete denominator and inclusion report."""
    events = [
        event
        async for event in AgentRunner(dependencies(FakeMonday())).stream_agent(
            "How healthy is the pipeline?", sid(35)
        )
    ]

    caveats = next(event for event in events if event.event == "caveats")
    assert caveats.caveats == []
    assert caveats.quality.total_rows == 2
    assert caveats.quality.included_rows == 2


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
            message, sid(20 + index)
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
        "Show pipeline for healthcare or energy", sid(30)
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
            "Show pipeline for healthcare or energy", sid(31)
        )
    ]

    assert [event.token for event in events if event.event == "token"] == [
        "Which sector should I use: Healthcare or Energy?"
    ]


@pytest.mark.asyncio
async def test_required_cross_board_auth_failure_emits_error_without_false_metrics() -> None:
    """A failed required board must never become empty evidence and yield false metrics."""

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
            "Which won deals have no work orders?", sid(32)
        )
    ]

    assert events[-1].event == "error"
    assert events[-1].code == "required_source_unavailable"
    assert "authentication failed" in events[-1].message
    assert "bearer-secret-value" not in events[-1].message
    source_event = next(event for event in events if event.event == "sources")
    caveat_event = next(event for event in events if event.event == "caveats")
    assert [(source.board_name, source.item_count, source.partial) for source in source_event.sources] == [
        ("Deals", 2, False),
        ("Work Orders", 0, True),
    ]
    assert "authentication failed" in " ".join(caveat_event.caveats)
    assert "bearer-secret-value" not in " ".join(caveat_event.caveats)
    assert events.index(source_event) < events.index(caveat_event) < len(events) - 1
    assert not any(event.event in {"token", "done"} for event in events)


@pytest.mark.asyncio
async def test_missing_required_board_id_preserves_successful_board_provenance() -> None:
    """Configuration failure on one board must not discard its concurrent peer result."""
    configured = settings().model_copy(update={"work_orders_board_id": ""})
    runner = AgentRunner(
        AgentDependencies(
            monday=FakeMonday(),
            settings=configured,
            clock=lambda: datetime(
                2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")
            ),
        )
    )

    events = [
        event
        async for event in runner.stream_agent(
            "Which won deals have no work orders?", sid(39)
        )
    ]

    sources = next(event for event in events if event.event == "sources")
    caveats = next(event for event in events if event.event == "caveats")
    assert [(source.board_name, source.item_count) for source in sources.sources] == [
        ("Deals", 2),
        ("Work Orders", 0),
    ]
    assert sources.sources[1].partial is True
    assert sources.sources[1].error == "Work Orders board is not configured."
    assert caveats.caveats == ["Work Orders board is not configured."]
    assert events[-1].event == "error"
    assert events[-1].code == "required_source_unavailable"
    assert not any(event.event in {"token", "done"} for event in events)


@pytest.mark.asyncio
async def test_single_board_partial_pages_compute_with_sanitized_partial_provenance() -> None:
    """Usable page-one rows may compute, but partial provenance must be explicit and safe."""
    events = [
        event
        async for event in AgentRunner(dependencies(PartialPagesMonday())).stream_agent(
            "How healthy is the pipeline?", sid(33)
        )
    ]

    sources = next(event for event in events if event.event == "sources")
    caveats = next(event for event in events if event.event == "caveats")
    assert sources.sources[0].partial is True
    assert sources.sources[0].error == "monday.com returned partial board results."
    assert "super-secret-token" not in " ".join(caveats.caveats)
    assert caveats.quality.total_rows == 2
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
            "Which won deals have no work orders?", sid(34)
        )
    ]

    assert events[-1].event == "error"
    assert events[-1].code == "required_source_unavailable"
    assert "rate-limited" in events[-1].message
    assert "HTTP 429" not in events[-1].message


@pytest.mark.asyncio
async def test_openai_failed_terminal_emits_sanitized_error_without_filler_or_done() -> None:
    """A provider failure terminal is not a successful empty qualitative context."""

    class FailedStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def __aiter__(self):
            async def events():
                yield type(
                    "FailedEvent",
                    (),
                    {
                        "type": "response.failed",
                        "response": type(
                            "FailedResponse",
                            (),
                            {
                                "error": type(
                                    "Failure",
                                    (),
                                    {"message": "Bearer provider-secret"},
                                )()
                            },
                        )(),
                    },
                )()

            return events()

    responses = type(
        "Responses",
        (),
        {"stream": lambda self, **kwargs: FailedStream()},
    )()
    llm = OpenAIService(
        settings().model_copy(update={"openai_api_key": "test-key"}),
        client=type("Client", (), {"responses": responses})(),
    )
    runner = AgentRunner(
        AgentDependencies(
            monday=FakeMonday(),
            settings=settings(),
            llm=llm,
            clock=lambda: datetime(
                2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")
            ),
        )
    )

    events = [
        event
        async for event in runner.stream_agent(
            "How healthy is the pipeline?", sid(40)
        )
    ]
    tokens = "".join(event.token for event in events if event.event == "token")

    assert events[-1].event == "error"
    assert "provider-secret" not in events[-1].message
    assert "normalized live board fields" not in tokens
    assert "Material caveat:" not in tokens
    assert not any(event.event == "done" for event in events)


@pytest.mark.asyncio
async def test_unconfigured_provider_error_uses_provider_neutral_wording() -> None:
    """The public configuration error must remain true for either supported provider."""
    configured = settings().model_copy(
        update={"deterministic_synthesis_fallback": False}
    )
    runner = AgentRunner(
        AgentDependencies(
            monday=FakeMonday(),
            settings=configured,
            clock=lambda: datetime(
                2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")
            ),
        )
    )

    events = [
        event
        async for event in runner.stream_agent(
            "How healthy is the pipeline?", sid(41)
        )
    ]

    assert events[-1].event == "error"
    assert events[-1].message == (
        "The language model is not configured and deterministic fallback is disabled."
    )
