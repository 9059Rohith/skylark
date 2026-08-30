"""Typed request and server-sent event contracts shared with the frontend."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.cleaning import DataQualityReport
from app.leadership.update_builder import LeadershipUpdate


def validate_session_id(value: str) -> str:
    """Require canonical, high-entropy UUIDv4 identifiers."""
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError("session_id must be a UUIDv4") from error
    if parsed.version != 4 or str(parsed) != value.casefold():
        raise ValueError("session_id must be a canonical UUIDv4")
    return value.casefold()


SessionId = Annotated[str, AfterValidator(validate_session_id)]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    session_id: SessionId

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
    quality: DataQualityReport | None = None


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
