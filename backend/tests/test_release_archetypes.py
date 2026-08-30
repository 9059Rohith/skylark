from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import AgentRunner
from app.main import create_app
from tests.test_agent_graph import FakeMonday, dependencies, settings


@pytest.mark.parametrize(
    ("prompt", "intent", "source_names", "leadership_event"),
    [
        ("How healthy is our pipeline?", "pipeline_health", {"Deals"}, False),
        ("What revenue did we win?", "revenue", {"Deals"}, False),
        (
            "Which won deals have no work orders?",
            "won_without_work_orders",
            {"Deals", "Work Orders"},
            False,
        ),
        (
            "What is average work order completion time?",
            "work_order_completion",
            {"Work Orders"},
            False,
        ),
        (
            "How many deals are missing close dates?",
            "data_quality",
            {"Deals"},
            False,
        ),
        (
            "Draft the weekly leadership update",
            "leadership_update",
            {"Deals", "Work Orders"},
            True,
        ),
    ],
)
def test_mocked_live_client_exercises_each_archetype_through_fastapi_sse(
    prompt: str,
    intent: str,
    source_names: set[str],
    leadership_event: bool,
) -> None:
    """Every evaluator archetype must cross the public API with its provenance."""
    runner = AgentRunner(dependencies(FakeMonday()))

    with TestClient(create_app(agent=runner, settings=settings())) as client:
        response = client.post(
            "/chat",
            json={"message": prompt, "session_id": str(uuid4())},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert f'"intent":"{intent}"' in response.text
    assert "event: error" not in response.text
    assert "event: done" in response.text
    assert {
        name
        for name in ("Deals", "Work Orders")
        if f'"board_name":"{name}"' in response.text
    } == source_names
    assert ("event: leadership_update" in response.text) is leadership_event
