import asyncio
from datetime import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import AgentDependencies, AgentRunner
from app.config import Settings
from tests.test_agent_graph import FakeMonday


def sid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


class RecordingSaver(InMemorySaver):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []
        self.checkpoints: list[dict[str, Any]] = []

    async def aput(self, config, checkpoint, metadata, new_versions):
        self.checkpoints.append(checkpoint)
        return await super().aput(config, checkpoint, metadata, new_versions)

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)
        await super().adelete_thread(thread_id)


def deps(
    saver: RecordingSaver, now: list[float], *, max_sessions: int = 2, ttl: float = 10
) -> AgentDependencies:
    return AgentDependencies(
        monday=FakeMonday(),
        settings=Settings(
            MONDAY_DEALS_BOARD_ID="101",
            MONDAY_WORK_ORDERS_BOARD_ID="202",
            deterministic_synthesis_fallback=True,
            checkpoint_max_sessions=max_sessions,
            checkpoint_session_ttl_seconds=ttl,
        ),
        clock=lambda: datetime(2026, 8, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        monotonic=lambda: now[0],
        checkpointer_factory=lambda: saver,
    )


@pytest.mark.asyncio
async def test_runner_rejects_non_uuid4_session_ids() -> None:
    """Internal callers must not bypass the API's high-entropy session boundary."""
    runner = AgentRunner(deps(RecordingSaver(), [0]))

    with pytest.raises(ValueError, match="UUIDv4"):
        await runner.run_agent("How healthy is the pipeline?", "predictable-session")


@pytest.mark.asyncio
async def test_session_registry_prunes_lru_and_expired_checkpoint_threads() -> None:
    """Unbounded in-memory checkpoints would allow session-driven memory exhaustion."""
    saver = RecordingSaver()
    now = [0.0]
    runner = AgentRunner(deps(saver, now))
    for index in (1, 2):
        now[0] = float(index - 1)
        await runner.run_agent("How healthy is the pipeline?", sid(index))

    now[0] = 2.0
    await runner.run_agent("How healthy is the pipeline?", sid(3))
    assert saver.deleted == [sid(1)]

    now[0] = 20.0
    await runner.run_agent("How healthy is the pipeline?", sid(3))
    assert saver.deleted == [sid(1), sid(2), sid(3)]


@pytest.mark.asyncio
async def test_checkpoint_does_not_retain_raw_message_or_client_history() -> None:
    """No historical superstep may retain the raw prompt as graph state."""
    saver = RecordingSaver()
    runner = AgentRunner(deps(saver, [0]))
    session_id = sid(7)
    raw_prompt = "How healthy is the confidential nebula pipeline?"

    await runner.run_agent(raw_prompt, session_id)
    state = await runner.graph.aget_state(
        {"configurable": {"thread_id": session_id}}
    )

    assert "message" not in state.values
    assert "session_id" not in state.values
    assert "history" not in state.values
    assert saver.checkpoints
    assert all(raw_prompt not in json.dumps(checkpoint, default=str) for checkpoint in saver.checkpoints)


@pytest.mark.asyncio
async def test_clarification_checkpoint_retains_only_derived_pending_context() -> None:
    """A terminal clarification must clear the raw user text before checkpointing."""
    runner = AgentRunner(deps(RecordingSaver(), [0]))
    session_id = sid(8)

    await runner.run_agent(
        "Show pipeline for healthcare or energy with confidential wording", session_id
    )
    state = await runner.graph.aget_state(
        {"configurable": {"thread_id": session_id}}
    )

    assert "message" not in state.values
    assert "session_id" not in state.values
    assert state.values["pending_clarification"]["options"] == [
        "Healthcare",
        "Energy",
    ]


@pytest.mark.asyncio
async def test_active_session_is_pinned_and_excess_concurrency_is_rejected_cleanly() -> None:
    """A capacity eviction must never delete the thread of an in-flight request."""

    class BlockingMonday(FakeMonday):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def get_board_items(self, board_id: str):
            self.entered.set()
            await self.release.wait()
            return await super().get_board_items(board_id)

    saver = RecordingSaver()
    now = [0.0]
    dependencies = deps(saver, now, max_sessions=1)
    monday = BlockingMonday()
    dependencies = AgentDependencies(
        monday=monday,
        settings=dependencies.settings,
        clock=dependencies.clock,
        monotonic=dependencies.monotonic,
        checkpointer_factory=dependencies.checkpointer_factory,
    )
    runner = AgentRunner(dependencies)
    first = asyncio.create_task(
        runner.run_agent("How healthy is the pipeline?", sid(10))
    )
    await monday.entered.wait()

    async def collect_second() -> list[Any]:
        return [
            event
            async for event in runner.stream_agent(
                "How healthy is the pipeline?", sid(11)
            )
        ]

    try:
        second_events = await asyncio.wait_for(collect_second(), timeout=0.5)
    finally:
        monday.release.set()
        await first

    assert [event.event for event in second_events] == ["error"]
    assert second_events[0].code == "session_capacity"
    assert saver.deleted == []
    assert sid(11) not in saver.storage
    assert sid(10) in saver.storage
