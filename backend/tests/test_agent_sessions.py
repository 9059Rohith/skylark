from datetime import datetime
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
    """The checkpoint needs derived context, not redundant raw conversation content."""
    runner = AgentRunner(deps(RecordingSaver(), [0]))
    session_id = sid(7)

    await runner.run_agent("How healthy is the pipeline?", session_id)
    state = await runner.graph.aget_state(
        {"configurable": {"thread_id": session_id}}
    )

    assert state.values["message"] == ""
    assert "history" not in state.values


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

    assert state.values["message"] == ""
    assert state.values["pending_clarification"]["options"] == [
        "Healthcare",
        "Energy",
    ]
