"""Provider-selectable official LLM adapters for routing help and synthesis."""

from collections.abc import AsyncIterator, Mapping
import json
from typing import Any

from openai import AsyncOpenAI

from app.agent.claude import ClaudeService
from app.agent.prompts import INTENT_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT
from app.config import Settings


class OpenAIService:
    """Bounded OpenAI Responses API adapter with true text-delta streaming."""

    configured = True

    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        if not settings.openai_api_key and client is None:
            raise ValueError("OPENAI_API_KEY is required for OpenAIService")
        self._model = settings.openai_model
        self._max_tokens = settings.openai_max_tokens
        self._owns_client = client is None
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    async def parse_intent(
        self, message: str, context: dict[str, Any]
    ) -> Mapping[str, Any] | None:
        response = await self._client.responses.create(
            model=self._model,
            max_output_tokens=min(self._max_tokens, 256),
            instructions=INTENT_SYSTEM_PROMPT,
            input=json.dumps(
                {"message": message, "prior_context": context},
                default=str,
                separators=(",", ":"),
            ),
            store=False,
        )
        try:
            value = json.loads(response.output_text)
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, Mapping) else None

    async def stream_synthesis(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        async with self._client.responses.stream(
            model=self._model,
            max_output_tokens=self._max_tokens,
            instructions=SYNTHESIS_SYSTEM_PROMPT,
            input=json.dumps(payload, default=str, separators=(",", ":")),
            store=False,
        ) as stream:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    yield event.delta

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()


def create_llm_service(
    settings: Settings,
    *,
    openai_client: AsyncOpenAI | None = None,
    anthropic_client: Any | None = None,
) -> OpenAIService | ClaudeService:
    """Construct only the adapter selected by LLM_PROVIDER."""
    if settings.llm_provider == "anthropic":
        return ClaudeService(settings, client=anthropic_client)
    return OpenAIService(settings, client=openai_client)
