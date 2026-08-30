from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api_models import (
    CaveatsEvent,
    DoneEvent,
    LeadershipUpdateEvent,
    SourcesEvent,
    StatusEvent,
    TokenEvent,
)
from app.config import Settings
from app.leadership.update_builder import LeadershipUpdate
from app.main import create_app


class FakeStreamingAgent:
    async def stream_agent(
        self, message: str, session_id: str, history: list[dict[str, str]]
    ) -> AsyncIterator[object]:
        yield StatusEvent(stage="fetch_from_monday", message="Reading boards")
        yield SourcesEvent(
            sources=[{"board_id": "101", "board_name": "Deals", "item_count": 2}]
        )
        yield CaveatsEvent(caveats=["1 row excluded from the headline metric."])
        yield LeadershipUpdateEvent(
            leadership_update=LeadershipUpdate(
                headline_pipeline_value_inr="21000000",
                sector_breakdown=[],
                notable_at_risk=[],
                quality_footnote="1 row excluded.",
                markdown="# Leadership update (draft)",
            )
        )
        yield TokenEvent(token="Direct answer first.")
        yield DoneEvent(session_id=session_id, intent="leadership_update")


def api_settings() -> Settings:
    return Settings(
        deals_board_id="101",
        work_orders_board_id="202",
        deterministic_synthesis_fallback=True,
        cors_allow_origins=("https://signal.example",),
        max_message_length=40,
        max_history_messages=2,
    )


def test_health_is_ready_without_exposing_configuration_or_secrets() -> None:
    """Health output must be useful to hosting without leaking credentials."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_streams_every_typed_sse_event_with_board_counts() -> None:
    """Dropping event types breaks the frontend evidence and draft reducers."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    response = client.post(
        "/chat", json={"message": "Draft leadership update", "session_id": "session-7"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [line for line in response.text.splitlines() if line.startswith("event:")] == [
        "event: status",
        "event: sources",
        "event: caveats",
        "event: leadership_update",
        "event: token",
        "event: done",
    ]
    assert '"board_name":"Deals","item_count":2' in response.text


def test_chat_rejects_invalid_session_message_and_history_bounds() -> None:
    """Unbounded or malformed caller input must never enter the agent graph."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    bad_session = client.post("/chat", json={"message": "hello", "session_id": "bad id!"})
    long_message = client.post(
        "/chat", json={"message": "x" * 41, "session_id": "valid-session"}
    )
    long_history = client.post(
        "/chat",
        json={
            "message": "hello",
            "session_id": "valid-session",
            "history": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
            ],
        },
    )

    assert bad_session.status_code == 422
    assert long_message.status_code == 422
    assert long_history.status_code == 422


def test_chat_rejects_whitespace_only_message() -> None:
    """Whitespace is not a meaningful message and must not consume agent resources."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    response = client.post(
        "/chat", json={"message": "   ", "session_id": "valid-session"}
    )

    assert response.status_code == 422


def test_cors_is_allow_listed_from_settings() -> None:
    """A permissive origin would expose authenticated backend access cross-site."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    allowed = client.options(
        "/chat",
        headers={
            "Origin": "https://signal.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    denied = client.options(
        "/chat",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "https://signal.example"
    assert "access-control-allow-origin" not in denied.headers
