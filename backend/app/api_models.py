"""Typed request and server-sent event contracts shared with the frontend."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.leadership.update_builder import LeadershipUpdate


SessionId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    session_id: SessionId
    history: list[HistoryMessage] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def message_must_have_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must contain non-whitespace text")
        return value


class Source(BaseModel):
    board_id: str
    board_name: str
    item_count: int = Field(ge=0)
    partial: bool = False
    error: str | None = None


class StatusEvent(BaseModel):
    event: Literal["status"] = "status"
    stage: str
    message: str


class SourcesEvent(BaseModel):
    event: Literal["sources"] = "sources"
    sources: list[Source]


class CaveatsEvent(BaseModel):
    event: Literal["caveats"] = "caveats"
    caveats: list[str]


class LeadershipUpdateEvent(BaseModel):
    event: Literal["leadership_update"] = "leadership_update"
    leadership_update: LeadershipUpdate


class TokenEvent(BaseModel):
    event: Literal["token"] = "token"
    token: str


class DoneEvent(BaseModel):
    event: Literal["done"] = "done"
    session_id: str
    intent: str


class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    code: str
    message: str


SSEEvent = (
    StatusEvent
    | SourcesEvent
    | CaveatsEvent
    | LeadershipUpdateEvent
    | TokenEvent
    | DoneEvent
    | ErrorEvent
)
