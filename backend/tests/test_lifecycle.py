from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
import pytest

from app.api_models import DoneEvent
from app.agent.graph import AgentDependencies, AgentRunner
from app.config import Settings
from app.main import create_app
from tests.test_agent_graph import FakeMonday


class LifecycleAgent:
    def __init__(self, *, warm_error: Exception | None = None) -> None:
        self.warmed = 0
        self.closed = 0
        self.warm_error = warm_error

    async def warmup(self) -> None:
        self.warmed += 1
        if self.warm_error:
            raise self.warm_error

    async def aclose(self) -> None:
        self.closed += 1

    async def stream_agent(self, message: str, session_id: str) -> AsyncIterator[object]:
        yield DoneEvent(session_id=session_id, intent="pipeline_health")


def complete_settings() -> Settings:
    return Settings(
        MONDAY_DEALS_BOARD_ID="101",
        MONDAY_WORK_ORDERS_BOARD_ID="202",
        monday_api_token="monday-secret",
        openai_api_key="openai-secret",
    )


def test_injected_agent_is_neither_warmed_nor_closed_by_app() -> None:
    """Dependency injection does not transfer lifecycle ownership to FastAPI."""
    agent = LifecycleAgent()

    with TestClient(create_app(agent=agent, settings=complete_settings())):
        pass

    assert agent.warmed == 0
    assert agent.closed == 0


def test_owned_agent_is_warmed_and_closed_by_lifespan(monkeypatch) -> None:
    """The production-owned clients must warm schemas and close transports."""
    agent = LifecycleAgent()
    monkeypatch.setattr("app.main._default_agent", lambda settings: agent)

    with TestClient(create_app(settings=complete_settings())) as client:
        assert agent.warmed == 1
        assert client.get("/health").json()["status"] == "ready"

    assert agent.closed == 1


def test_schema_warmup_failure_degrades_health_without_exception_details(monkeypatch) -> None:
    """Startup transport failure must be visible without leaking its raw exception."""
    agent = LifecycleAgent(warm_error=RuntimeError("bearer startup-secret"))
    monkeypatch.setattr("app.main._default_agent", lambda settings: agent)

    with TestClient(create_app(settings=complete_settings())) as client:
        response = client.get("/health")

    assert response.json() == {
        "status": "degraded",
        "missing": ["MONDAY_SCHEMA_ACCESS"],
    }
    assert "startup-secret" not in response.text
    assert agent.closed == 1


@pytest.mark.asyncio
async def test_runner_warms_both_schemas_and_closes_only_owned_dependencies() -> None:
    """Ownership must flow through the runner without closing caller-injected fakes."""

    class ClosableMonday(FakeMonday):
        def __init__(self) -> None:
            super().__init__()
            self.schemas: list[str] = []
            self.closed = 0

        async def get_board_schema(self, board_id: str):
            self.schemas.append(board_id)
            return await super().get_board_schema(board_id)

        async def aclose(self) -> None:
            self.closed += 1

    class ClosableClaude:
        configured = True

        def __init__(self) -> None:
            self.closed = 0

        async def aclose(self) -> None:
            self.closed += 1

    monday = ClosableMonday()
    claude = ClosableClaude()
    settings = complete_settings()
    owned = AgentRunner(
        AgentDependencies(monday=monday, settings=settings, llm=claude),
        owns_dependencies=True,
    )
    await owned.warmup()
    await owned.aclose()

    assert monday.schemas == ["101", "202"]
    assert monday.closed == 1
    assert claude.closed == 1

    injected_monday = ClosableMonday()
    injected = AgentRunner(
        AgentDependencies(monday=injected_monday, settings=settings),
        owns_dependencies=False,
    )
    await injected.aclose()
    assert injected_monday.closed == 0


@pytest.mark.asyncio
async def test_runner_closes_each_owned_provider_even_when_one_close_fails() -> None:
    """One provider cleanup failure must not skip the other owned provider."""

    class FailingCloseMonday(FakeMonday):
        async def aclose(self) -> None:
            raise RuntimeError("monday close failed")

    class RecordingClaude:
        configured = True

        def __init__(self) -> None:
            self.closed = 0

        async def aclose(self) -> None:
            self.closed += 1

    claude = RecordingClaude()
    runner = AgentRunner(
        AgentDependencies(
            monday=FailingCloseMonday(), settings=complete_settings(), llm=claude
        ),
        owns_dependencies=True,
    )

    await runner.aclose()

    assert claude.closed == 1
