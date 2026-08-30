from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.claude import ClaudeService
from app.agent.llm import OpenAIService, create_llm_service
from app.config import Settings


class FakeResponseStream:
    def __init__(self) -> None:
        self.events = (
            SimpleNamespace(type="response.created"),
            SimpleNamespace(type="response.output_text.delta", delta="First context. "),
            SimpleNamespace(type="response.output_text.delta", delta="Second context."),
            SimpleNamespace(type="response.completed"),
        )

    async def __aenter__(self) -> "FakeResponseStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self):
        async def iterate():
            for event in self.events:
                yield event

        return iterate()


class FakeResponses:
    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.stream_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return SimpleNamespace(output_text='{"intent":"data_quality"}')

    def stream(self, **kwargs: Any) -> FakeResponseStream:
        self.stream_kwargs = kwargs
        return FakeResponseStream()


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_openai_service_uses_responses_api_for_json_and_progressive_deltas() -> None:
    """OpenAI must use Responses output text, including real output_text.delta events."""
    client = FakeOpenAIClient()
    service = OpenAIService(
        Settings(
            openai_api_key="test-key",
            openai_model="gpt-5.4-mini",
            openai_max_tokens=333,
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
    assert client.responses.create_kwargs["model"] == "gpt-5.4-mini"
    assert client.responses.create_kwargs["max_output_tokens"] == 256
    assert client.responses.create_kwargs["store"] is False
    assert "intent-v1" in client.responses.create_kwargs["instructions"]
    assert client.responses.stream_kwargs["max_output_tokens"] == 333
    assert "synthesis-v1" in client.responses.stream_kwargs["instructions"]
    assert deltas == ["First context. ", "Second context."]


def test_llm_provider_defaults_to_openai_and_can_select_anthropic() -> None:
    """One env setting must select either official provider adapter."""
    openai_client = FakeOpenAIClient()
    default_service = create_llm_service(
        Settings(openai_api_key="openai-key"), openai_client=openai_client
    )
    anthropic_service = create_llm_service(
        Settings(llm_provider="anthropic", anthropic_api_key="anthropic-key"),
        anthropic_client=SimpleNamespace(messages=SimpleNamespace()),
    )

    assert Settings().llm_provider == "openai"
    assert Settings().openai_model == "gpt-5.4-mini"
    assert isinstance(default_service, OpenAIService)
    assert isinstance(anthropic_service, ClaudeService)


@pytest.mark.asyncio
async def test_openai_service_closes_only_the_client_it_constructs(monkeypatch) -> None:
    """Injected fakes remain caller-owned; production-created SDK clients are closed."""
    injected = FakeOpenAIClient()
    injected_service = OpenAIService(
        Settings(openai_api_key="test-key"), client=injected
    )
    await injected_service.aclose()
    assert injected.closed == 0

    owned = FakeOpenAIClient()
    monkeypatch.setattr("app.agent.llm.AsyncOpenAI", lambda **kwargs: owned)
    owned_service = OpenAIService(Settings(openai_api_key="test-key"))
    await owned_service.aclose()
    assert owned.closed == 1
