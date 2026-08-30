"""Hand-rolled LangGraph definition and checkpointed runner."""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentServiceError, GraphNodes
from app.agent.state import AgentContext, AgentState
from app.api_models import (
    CaveatsEvent,
    DoneEvent,
    ErrorEvent,
    LeadershipUpdateEvent,
    SourcesEvent,
    StatusEvent,
    TokenEvent,
    validate_session_id,
)
from app.config import Settings
from app.leadership import LeadershipUpdate
from app.monday import MondayClient


class LLMBoundary(Protocol):
    configured: bool

    async def parse_intent(self, message: str, context: dict[str, Any]) -> Any: ...

    def stream_synthesis(self, payload: dict[str, Any]) -> AsyncIterator[str]: ...


def create_checkpointer() -> Any:
    """Local checkpointer factory; replace this callable with a Postgres saver in production."""
    return InMemorySaver()


def _default_clock(settings: Settings) -> Callable[[], datetime]:
    return lambda: datetime.now(ZoneInfo(settings.app_timezone))


@dataclass(frozen=True)
class AgentDependencies:
    monday: MondayClient
    settings: Settings
    llm: LLMBoundary | None = None
    clock: Callable[[], datetime] | None = None
    monotonic: Callable[[], float] = time.monotonic
    checkpointer_factory: Callable[[], Any] = field(default=create_checkpointer)

    def __post_init__(self) -> None:
        if self.clock is None:
            object.__setattr__(self, "clock", _default_clock(self.settings))


def build_graph(dependencies: AgentDependencies, *, checkpointer: Any | None = None) -> Any:
    """Build the required named graph with one conditional clarification exit."""
    nodes = GraphNodes(dependencies)
    builder = StateGraph(AgentState, context_schema=AgentContext)
    builder.add_node("parse_intent", nodes.parse_intent)
    builder.add_node("clarify", nodes.clarify)
    builder.add_node("plan_data_needs", nodes.plan_data_needs)
    builder.add_node("fetch_from_monday", nodes.fetch_from_monday)
    builder.add_node("clean_and_normalize", nodes.clean_and_normalize)
    builder.add_node("analyze", nodes.analyze)
    builder.add_node("synthesize_answer", nodes.synthesize_answer)
    builder.add_node("format_response", nodes.format_response)
    builder.add_edge(START, "parse_intent")
    builder.add_conditional_edges(
        "parse_intent",
        lambda state: "clarify" if state.get("clarification_question") else "continue",
        {"clarify": "clarify", "continue": "plan_data_needs"},
    )
    builder.add_edge("clarify", END)
    builder.add_edge("plan_data_needs", "fetch_from_monday")
    builder.add_edge("fetch_from_monday", "clean_and_normalize")
    builder.add_edge("clean_and_normalize", "analyze")
    builder.add_edge("analyze", "synthesize_answer")
    builder.add_edge("synthesize_answer", "format_response")
    builder.add_edge("format_response", END)
    return builder.compile(checkpointer=checkpointer or dependencies.checkpointer_factory())


_STATUS_MESSAGES = {
    "parse_intent": "Understanding the question",
    "plan_data_needs": "Planning the board reads",
    "fetch_from_monday": "Reading monday.com boards",
    "clean_and_normalize": "Normalizing live board fields",
    "analyze": "Computing deterministic metrics",
    "synthesize_answer": "Writing the answer",
    "format_response": "Finalizing evidence",
    "clarify": "Clarification needed",
}


class AgentRunner:
    """Own one compiled graph so session checkpoints survive between requests."""

    def __init__(
        self, dependencies: AgentDependencies, *, owns_dependencies: bool = False
    ) -> None:
        self._dependencies = dependencies
        self._owns_dependencies = owns_dependencies
        checkpointer = dependencies.checkpointer_factory()
        self.graph = build_graph(dependencies, checkpointer=checkpointer)
        self._sessions = _SessionRegistry(
            checkpointer=checkpointer,
            max_sessions=dependencies.settings.checkpoint_max_sessions,
            ttl_seconds=dependencies.settings.checkpoint_session_ttl_seconds,
            monotonic=dependencies.monotonic,
        )

    async def warmup(self) -> None:
        """Warm both configured schemas before serving production traffic."""
        await asyncio.gather(
            self._dependencies.monday.get_board_schema(
                self._dependencies.settings.deals_board_id
            ),
            self._dependencies.monday.get_board_schema(
                self._dependencies.settings.work_orders_board_id
            ),
        )

    async def aclose(self) -> None:
        """Close dependencies only when this runner owns their lifecycle."""
        if not self._owns_dependencies:
            return
        monday_close = getattr(self._dependencies.monday, "aclose", None)
        llm_close = getattr(self._dependencies.llm, "aclose", None)
        closers = [close() for close in (monday_close, llm_close) if close is not None]
        if closers:
            await asyncio.gather(*closers, return_exceptions=True)

    async def run_agent(
        self, message: str, session_id: str
    ) -> dict[str, Any]:
        session_id = validate_session_id(session_id)
        await self._sessions.acquire(session_id)
        try:
            return await self.graph.ainvoke(
                {},
                config={"configurable": {"thread_id": session_id}},
                context={"message": message, "session_id": session_id},
            )
        finally:
            await self._sessions.release(session_id)

    async def stream_agent(
        self, message: str, session_id: str
    ) -> AsyncIterator[object]:
        final_update: dict[str, Any] = {}
        acquired = False
        normalized_session_id = session_id
        try:
            normalized_session_id = validate_session_id(session_id)
            await self._sessions.acquire(normalized_session_id)
            acquired = True
            async for mode, chunk in self.graph.astream(
                {},
                config={"configurable": {"thread_id": normalized_session_id}},
                context={"message": message, "session_id": normalized_session_id},
                stream_mode=["updates", "custom"],
            ):
                if mode == "custom" and chunk.get("event") == "token":
                    yield TokenEvent(token=str(chunk["token"]))
                    continue
                if mode != "updates":
                    continue
                for node_name, update in chunk.items():
                    if node_name in _STATUS_MESSAGES:
                        yield StatusEvent(stage=node_name, message=_STATUS_MESSAGES[node_name])
                    if isinstance(update, dict):
                        final_update.update(update)
                        if node_name == "fetch_from_monday":
                            yield SourcesEvent(sources=update.get("sources", []))
                        if node_name == "analyze":
                            yield CaveatsEvent(
                                caveats=update.get("caveats", []),
                                quality=update.get("analysis", {}).get("quality"),
                            )
                            if update.get("leadership_update"):
                                yield LeadershipUpdateEvent(
                                    leadership_update=LeadershipUpdate.model_validate(
                                        update["leadership_update"]
                                    )
                                )
            yield DoneEvent(
                session_id=normalized_session_id,
                intent=str(final_update.get("intent", "unknown")),
            )
        except AgentServiceError as error:
            if error.sources:
                yield SourcesEvent(sources=error.sources)
            if error.caveats or error.quality is not None:
                yield CaveatsEvent(caveats=error.caveats, quality=error.quality)
            yield ErrorEvent(code=error.code, message=str(error))
        except Exception:
            yield ErrorEvent(
                code="internal_error",
                message="The request could not be completed. Please try again.",
            )
        finally:
            if acquired:
                await self._sessions.release(normalized_session_id)


class _SessionRegistry:
    def __init__(
        self,
        *,
        checkpointer: Any,
        max_sessions: int,
        ttl_seconds: float,
        monotonic: Callable[[], float],
    ) -> None:
        self._checkpointer = checkpointer
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._sessions: OrderedDict[str, _SessionEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def acquire(self, session_id: str) -> None:
        async with self._lock:
            now = self._monotonic()
            expired = [
                thread_id
                for thread_id, entry in self._sessions.items()
                if entry.active == 0 and now - entry.last_seen >= self._ttl_seconds
            ]
            for thread_id in expired:
                await self._checkpointer.adelete_thread(thread_id)
                self._sessions.pop(thread_id, None)
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry.active += 1
                entry.last_seen = now
                self._sessions.move_to_end(session_id)
                return
            if len(self._sessions) >= self._max_sessions:
                inactive = next(
                    (
                        thread_id
                        for thread_id, candidate in self._sessions.items()
                        if candidate.active == 0
                    ),
                    None,
                )
                if inactive is None:
                    raise AgentServiceError(
                        "The server is at its active session limit. Please retry shortly.",
                        code="session_capacity",
                    )
                await self._checkpointer.adelete_thread(inactive)
                self._sessions.pop(inactive, None)
            self._sessions[session_id] = _SessionEntry(last_seen=now, active=1)

    async def release(self, session_id: str) -> None:
        async with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return
            entry.active = max(0, entry.active - 1)
            entry.last_seen = self._monotonic()
            self._sessions.move_to_end(session_id)


@dataclass
class _SessionEntry:
    last_seen: float
    active: int = 0


_default_runner: AgentRunner | None = None


async def run_agent(
    message: str,
    session_id: str,
    *,
    dependencies: AgentDependencies | None = None,
) -> dict[str, Any]:
    """Run through a process-level checkpointed runner, optionally initializing it."""
    global _default_runner
    if dependencies is not None:
        _default_runner = AgentRunner(dependencies)
    if _default_runner is None:
        raise AgentServiceError(
            "The default agent runner has not been configured.", code="configuration"
        )
    return await _default_runner.run_agent(message, session_id)
