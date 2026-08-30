from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.cleaning import DataQualityReport
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

SESSION_ID = "00000000-0000-4000-8000-000000000001"


class FakeStreamingAgent:
    async def stream_agent(self, message: str, session_id: str) -> AsyncIterator[object]:
        yield StatusEvent(stage="fetch_from_monday", message="Reading boards")
        yield SourcesEvent(
            sources=[{"board_id": "101", "board_name": "Deals", "item_count": 2}]
        )
        yield CaveatsEvent(
            caveats=["1 row excluded from the headline metric."],
            quality=DataQualityReport(
                total_rows=3,
                included_rows=2,
                exclusions={"invalid_currency": 1},
            ),
        )
        yield LeadershipUpdateEvent(
            leadership_update=LeadershipUpdate(
                headline_pipeline_value_inr="21000000",
                sector_breakdown=[],
                notable_at_risk=[],
                quality={
                    "pipeline": {"total_rows": 3, "included_rows": 2},
                    "sector": {"total_rows": 3, "included_rows": 2},
                    "gaps": {"total_rows": 4, "included_rows": 4},
                    "operational_risks": {"total_rows": 1, "included_rows": 1},
                },
                quality_footnote="1 row excluded.",
                markdown="# Leadership update (draft)",
            )
        )
        yield TokenEvent(token="Direct answer first.")
        yield DoneEvent(session_id=session_id, intent="leadership_update")


def api_settings() -> Settings:
    return Settings(
        MONDAY_DEALS_BOARD_ID="101",
        MONDAY_WORK_ORDERS_BOARD_ID="202",
        deterministic_synthesis_fallback=True,
        cors_allow_origins=("https://signal.example",),
        max_message_length=40,
    )


def test_health_is_degraded_without_exposing_configuration_or_secrets() -> None:
    """Health output must be useful to hosting without leaking credentials."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "missing": ["MONDAY_API_TOKEN", "OPENAI_API_KEY"],
    }


def test_health_reports_ready_only_when_all_required_configuration_exists() -> None:
    """Configured readiness must be explicit and contain no secret values."""
    settings = api_settings().model_copy(
        update={
            "monday_api_token": "monday-secret",
            "openai_api_key": "openai-secret",
        }
    )
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=settings))

    response = client.get("/health")

    assert response.json() == {"status": "ready", "missing": []}
    assert "secret" not in response.text


def test_health_lists_every_missing_required_integration_setting() -> None:
    """Missing board IDs must degrade readiness just like absent API credentials."""
    settings = Settings(
        MONDAY_DEALS_BOARD_ID="",
        MONDAY_WORK_ORDERS_BOARD_ID="",
        monday_api_token=None,
        openai_api_key=None,
    )
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=settings))

    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "missing": [
            "MONDAY_API_TOKEN",
            "MONDAY_DEALS_BOARD_ID",
            "MONDAY_WORK_ORDERS_BOARD_ID",
            "OPENAI_API_KEY",
        ],
    }


def test_health_uses_the_selected_anthropic_provider_key() -> None:
    """Readiness must require only the credential for the selected LLM adapter."""
    settings = Settings(
        llm_provider="anthropic",
        MONDAY_DEALS_BOARD_ID="101",
        MONDAY_WORK_ORDERS_BOARD_ID="202",
        monday_api_token="monday-secret",
        anthropic_api_key="anthropic-secret",
    )

    response = TestClient(
        create_app(agent=FakeStreamingAgent(), settings=settings)
    ).get("/health")

    assert response.json() == {"status": "ready", "missing": []}
    assert response.status_code == 200


def test_chat_streams_every_typed_sse_event_with_board_counts() -> None:
    """Dropping event types breaks the frontend evidence and draft reducers."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    response = client.post(
        "/chat", json={"message": "Draft leadership update", "session_id": SESSION_ID}
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
    assert '"quality":{"total_rows":3,"included_rows":2' in response.text


def test_chat_requires_uuid4_and_rejects_message_or_history_input() -> None:
    """Unbounded or malformed caller input must never enter the agent graph."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    bad_session = client.post("/chat", json={"message": "hello", "session_id": "bad id!"})
    wrong_uuid_version = client.post(
        "/chat",
        json={
            "message": "hello",
            "session_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        },
    )
    long_message = client.post(
        "/chat", json={"message": "x" * 41, "session_id": SESSION_ID}
    )
    supplied_history = client.post(
        "/chat",
        json={
            "message": "hello",
            "session_id": SESSION_ID,
            "history": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
            ],
        },
    )

    assert bad_session.status_code == 422
    assert wrong_uuid_version.status_code == 422
    assert long_message.status_code == 422
    assert supplied_history.status_code == 422


def test_chat_rejects_whitespace_only_message() -> None:
    """Whitespace is not a meaningful message and must not consume agent resources."""
    client = TestClient(create_app(agent=FakeStreamingAgent(), settings=api_settings()))

    response = client.post(
        "/chat", json={"message": "   ", "session_id": SESSION_ID}
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
