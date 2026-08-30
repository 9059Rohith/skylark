"""Bounded official Anthropic client used for graph reasoning and synthesis."""

from collections.abc import AsyncIterator, Mapping
import json
from typing import Any

from anthropic import AsyncAnthropic

from app.agent.prompts import INTENT_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT
from app.config import Settings


class ClaudeService:
    """Keep all external LLM calls behind a small injectable boundary."""

    configured = True

    def __init__(self, settings: Settings, *, client: AsyncAnthropic | None = None) -> None:
        if not settings.anthropic_api_key and client is None:
            raise ValueError("ANTHROPIC_API_KEY is required for ClaudeService")
        self._model = settings.anthropic_model
        self._max_tokens = settings.anthropic_max_tokens
        self._owns_client = client is None
        self._client = client or AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.anthropic_timeout_seconds,
            max_retries=settings.anthropic_max_retries,
        )

    async def parse_intent(
        self, message: str, context: dict[str, Any]
    ) -> Mapping[str, Any] | None:
        """Request structured routing advice; deterministic validation remains downstream."""
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=min(self._max_tokens, 256),
            system=INTENT_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {"message": message, "prior_context": context},
                        default=str,
                        separators=(",", ":"),
                    ),
                }
            ],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, Mapping) else None

    async def stream_synthesis(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        """Yield real Claude text deltas as soon as the SDK receives them."""
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(payload, default=str, separators=(",", ":")),
                }
            ],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def aclose(self) -> None:
        """Close only the SDK client constructed by this service."""
        if self._owns_client:
            await self._client.close()
