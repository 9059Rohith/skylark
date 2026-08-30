"""Provider-selectable official LLM adapters for routing help and synthesis."""

from collections.abc import AsyncIterator, Mapping
import json
from typing import Any

from openai import AsyncOpenAI

from app.agent.claude import ClaudeService
from app.agent.prompts import INTENT_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT
from app.config import Settings


class LLMProviderError(RuntimeError):
    """Sanitized provider failure safe to pass across the agent boundary."""


_PROVIDER_FAILURE = "The language model could not complete the response. Please try again."


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
        completed = False
        refusal_seen = False
        text_seen = False
        try:
            async with self._client.responses.stream(
                model=self._model,
                max_output_tokens=self._max_tokens,
                instructions=SYNTHESIS_SYSTEM_PROMPT,
                input=json.dumps(payload, default=str, separators=(",", ":")),
                store=False,
            ) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", "")
                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            text_seen = True
                            yield delta
                    elif event_type in {
                        "error",
                        "response.failed",
                        "response.incomplete",
                    }:
                        raise LLMProviderError(_PROVIDER_FAILURE)
                    elif event_type.startswith("response.refusal"):
                        refusal_seen = True
                    elif event_type == "response.completed":
                        completed = True
        except LLMProviderError:
            raise
        except Exception:
            raise LLMProviderError(_PROVIDER_FAILURE) from None
        if not completed or refusal_seen or not text_seen:
            raise LLMProviderError(_PROVIDER_FAILURE)

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
