"""FastAPI application factory and bounded SSE chat endpoint."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent.claude import ClaudeService
from app.agent.graph import AgentDependencies, AgentRunner
from app.api_models import ChatRequest, ErrorEvent, SSEEvent
from app.config import Settings
from app.monday import GraphQLMondayClient


class StreamingAgent(Protocol):
    def stream_agent(
        self, message: str, session_id: str, history: list[dict[str, str]]
    ) -> AsyncIterator[SSEEvent]: ...


class _UnavailableAgent:
    def __init__(self, message: str) -> None:
        self.message = message

    async def stream_agent(
        self, message: str, session_id: str, history: list[dict[str, str]]
    ) -> AsyncIterator[SSEEvent]:
        yield ErrorEvent(code="configuration", message=self.message)


def _default_agent(settings: Settings) -> StreamingAgent:
    if not settings.monday_api_token:
        return _UnavailableAgent("monday.com access is not configured on this server.")
    monday = GraphQLMondayClient(settings.monday_api_token)
    claude = ClaudeService(settings) if settings.anthropic_api_key else None
    return AgentRunner(AgentDependencies(monday=monday, settings=settings, claude=claude))


def _sse(event: Any) -> str:
    name = event.event
    return f"event: {name}\ndata: {event.model_dump_json()}\n\n"


def create_app(
    *, agent: StreamingAgent | None = None, settings: Settings | None = None
) -> FastAPI:
    """Create an injectable app so tests and local demos need no live credentials."""
    active_settings = settings or Settings()
    active_agent = agent or _default_agent(active_settings)
    application = FastAPI(title="Skylark Signal", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/chat")
    async def chat(request: ChatRequest) -> StreamingResponse:
        if len(request.message) > active_settings.max_message_length:
            raise HTTPException(status_code=422, detail="message exceeds configured limit")
        if len(request.history) > active_settings.max_history_messages:
            raise HTTPException(status_code=422, detail="history exceeds configured limit")
        if any(
            len(item.content) > active_settings.max_message_length
            for item in request.history
        ):
            raise HTTPException(status_code=422, detail="history message exceeds configured limit")

        async def events() -> AsyncIterator[str]:
            try:
                async for event in active_agent.stream_agent(
                    request.message,
                    request.session_id,
                    [item.model_dump() for item in request.history],
                ):
                    yield _sse(event)
            except Exception:
                yield _sse(
                    ErrorEvent(
                        code="internal_error",
                        message="The request could not be completed. Please try again.",
                    )
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return application


app = create_app()
