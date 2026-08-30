"""Hand-rolled LangGraph definition and checkpointed runner."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import AgentServiceError, GraphNodes
from app.agent.state import AgentState
from app.api_models import (
    CaveatsEvent,
    DoneEvent,
    ErrorEvent,
    LeadershipUpdateEvent,
    SourcesEvent,
    StatusEvent,
    TokenEvent,
)
from app.config import Settings
from app.leadership import LeadershipUpdate
from app.monday import MondayClient


class ClaudeBoundary(Protocol):
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
    claude: ClaudeBoundary | None = None
    clock: Callable[[], datetime] | None = None
    checkpointer_factory: Callable[[], Any] = field(default=create_checkpointer)

    def __post_init__(self) -> None:
        if self.clock is None:
            object.__setattr__(self, "clock", _default_clock(self.settings))


def build_graph(dependencies: AgentDependencies, *, checkpointer: Any | None = None) -> Any:
    """Build the required named graph with one conditional clarification exit."""
    nodes = GraphNodes(dependencies)
    builder = StateGraph(AgentState)
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

    def __init__(self, dependencies: AgentDependencies) -> None:
        self.graph = build_graph(dependencies)

    async def run_agent(
        self, message: str, session_id: str, history: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        return await self.graph.ainvoke(
            {"message": message, "session_id": session_id, "history": history or []},
            config={"configurable": {"thread_id": session_id}},
        )

    async def stream_agent(
        self, message: str, session_id: str, history: list[dict[str, str]]
    ) -> AsyncIterator[object]:
        final_update: dict[str, Any] = {}
        try:
            async for mode, chunk in self.graph.astream(
                {"message": message, "session_id": session_id, "history": history},
                config={"configurable": {"thread_id": session_id}},
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
                            if update.get("caveats"):
                                yield CaveatsEvent(caveats=update["caveats"])
                            if update.get("leadership_update"):
                                yield LeadershipUpdateEvent(
                                    leadership_update=LeadershipUpdate.model_validate(
                                        update["leadership_update"]
                                    )
                                )
            yield DoneEvent(
                session_id=session_id,
                intent=str(final_update.get("intent", "unknown")),
            )
        except AgentServiceError as error:
            yield ErrorEvent(code=error.code, message=str(error))
        except Exception:
            yield ErrorEvent(
                code="internal_error",
                message="The request could not be completed. Please try again.",
            )


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
