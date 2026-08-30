from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.claude import ClaudeService
from app.config import Settings


class FakeStream:
    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    @property
    def text_stream(self) -> Any:
        async def deltas() -> Any:
            yield "Direct answer. "
            yield "Caveat last."

        return deltas()


class FakeMessages:
    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.stream_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"intent":"data_quality"}')]
        )

    def stream(self, **kwargs: Any) -> FakeStream:
        self.stream_kwargs = kwargs
        return FakeStream()


@pytest.mark.asyncio
async def test_claude_service_uses_versioned_bounded_structured_calls_and_deltas() -> None:
    """Wrong model/call shape or buffered output breaks the configured Claude contract."""
    messages = FakeMessages()
    client = SimpleNamespace(messages=messages)
    service = ClaudeService(
        Settings(
            anthropic_api_key="test-key",
            anthropic_model="claude-sonnet-5",
            anthropic_max_tokens=321,
        ),
        client=client,
    )

    decision = await service.parse_intent("Any quality issues?", {})
    deltas = [
        delta
        async for delta in service.stream_synthesis(
            {"intent": "data_quality", "metrics": {"missing": 2}}
        )
    ]

    assert decision == {"intent": "data_quality"}
    assert messages.create_kwargs["model"] == "claude-sonnet-5"
    assert messages.create_kwargs["max_tokens"] == 256
    assert "intent-v1" in messages.create_kwargs["system"]
    assert messages.stream_kwargs["max_tokens"] == 321
    assert "synthesis-v1" in messages.stream_kwargs["system"]
    assert deltas == ["Direct answer. ", "Caveat last."]


def test_deterministic_synthesis_fallback_is_off_by_default() -> None:
    """Production must never silently replace an unconfigured Claude call."""
    assert Settings().deterministic_synthesis_fallback is False
