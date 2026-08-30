"""FastAPI application factory and bounded SSE chat endpoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.agent.graph import AgentDependencies, AgentRunner
from app.agent.llm import create_llm_service
from app.api_models import ChatRequest, ErrorEvent, SSEEvent
from app.config import Settings
from app.monday import GraphQLMondayClient


class StreamingAgent(Protocol):
    def stream_agent(self, message: str, session_id: str) -> AsyncIterator[SSEEvent]: ...


class _UnavailableAgent:
    def __init__(self, message: str) -> None:
        self.message = message

    async def stream_agent(self, message: str, session_id: str) -> AsyncIterator[SSEEvent]:
        yield ErrorEvent(code="configuration", message=self.message)


def _default_agent(settings: Settings) -> StreamingAgent:
    if not settings.monday_api_token:
        return _UnavailableAgent("monday.com access is not configured on this server.")
    monday = GraphQLMondayClient(settings.monday_api_token)
    provider_key = (
        settings.anthropic_api_key
        if settings.llm_provider == "anthropic"
        else settings.openai_api_key
    )
    llm = create_llm_service(settings) if provider_key else None
    return AgentRunner(
        AgentDependencies(monday=monday, settings=settings, llm=llm),
        owns_dependencies=True,
    )


def _sse(event: Any) -> str:
    name = event.event
    return f"event: {name}\ndata: {event.model_dump_json()}\n\n"


def create_app(
    *, agent: StreamingAgent | None = None, settings: Settings | None = None
) -> FastAPI:
    """Create an injectable app so tests and local demos need no live credentials."""
    active_settings = settings or Settings()
    owns_agent = agent is None
    active_agent = agent if agent is not None else _default_agent(active_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.runtime_missing = []
        if owns_agent and hasattr(active_agent, "warmup"):
            try:
                await active_agent.warmup()
            except Exception:
                application.state.runtime_missing = ["MONDAY_SCHEMA_ACCESS"]
        try:
            yield
        finally:
            if owns_agent and hasattr(active_agent, "aclose"):
                await active_agent.aclose()

    application = FastAPI(
        title="Skylark Signal", version="0.1.0", lifespan=lifespan
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @application.get("/health")
    async def health() -> JSONResponse:
        missing = []
        if not active_settings.monday_api_token:
            missing.append("MONDAY_API_TOKEN")
        if not active_settings.deals_board_id:
            missing.append("MONDAY_DEALS_BOARD_ID")
        if not active_settings.work_orders_board_id:
            missing.append("MONDAY_WORK_ORDERS_BOARD_ID")
        if (
            active_settings.llm_provider == "anthropic"
            and not active_settings.anthropic_api_key
        ):
            missing.append("ANTHROPIC_API_KEY")
        if active_settings.llm_provider == "openai" and not active_settings.openai_api_key:
            missing.append("OPENAI_API_KEY")
        missing.extend(getattr(application.state, "runtime_missing", []))
        return JSONResponse(
            {"status": "degraded" if missing else "ready", "missing": missing},
            status_code=503 if missing else 200,
        )

    @application.post("/chat")
    async def chat(request: ChatRequest) -> StreamingResponse:
        if len(request.message) > active_settings.max_message_length:
            raise HTTPException(status_code=422, detail="message exceeds configured limit")

        async def events() -> AsyncIterator[str]:
            try:
                async for event in active_agent.stream_agent(
                    request.message,
                    request.session_id,
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
