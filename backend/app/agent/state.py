"""Typed graph state persisted by the LangGraph checkpointer."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    message: str
    session_id: str
    history: list[dict[str, str]]
    intent: str
    period: dict[str, Any] | None
    sector: str | None
    breakdown_by_sector: bool
    clarification_question: str | None
    required_boards: list[str]
    fetched: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    scope_exclusions: dict[str, dict[str, int]]
    sources: list[dict[str, Any]]
    caveats: list[str]
    analysis: dict[str, Any]
    answer: str
    leadership_update: dict[str, Any] | None
    node_trace: list[str]
