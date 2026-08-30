"""Environment-backed application settings with bounded public inputs."""

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Server configuration. Secret values are never included in health responses."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    monday_api_token: str | None = None
    deals_board_id: str = Field(default="", alias="MONDAY_DEALS_BOARD_ID")
    work_orders_board_id: str = Field(
        default="", alias="MONDAY_WORK_ORDERS_BOARD_ID"
    )
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    openai_max_retries: int = Field(default=2, ge=0, le=5)
    openai_max_tokens: int = Field(default=700, ge=64, le=4096)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    anthropic_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    anthropic_max_retries: int = Field(default=2, ge=0, le=5)
    anthropic_max_tokens: int = Field(default=700, ge=64, le=4096)
    llm_context_max_chars: int = Field(default=1200, ge=100, le=4000)
    deterministic_synthesis_fallback: bool = False
    usd_to_inr_rate: str | None = None
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    app_timezone: str = "Asia/Kolkata"
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:3000",
    )
    max_message_length: int = Field(default=4000, ge=1, le=20_000)
    checkpoint_max_sessions: int = Field(default=1000, ge=1, le=100_000)
    checkpoint_session_ttl_seconds: float = Field(
        default=3600.0, gt=0, le=2_592_000
    )

    @field_validator(
        "monday_api_token", "openai_api_key", "anthropic_api_key", mode="before"
    )
    @classmethod
    def empty_secret_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value
