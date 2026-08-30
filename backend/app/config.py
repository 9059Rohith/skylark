"""Environment-backed application settings with bounded public inputs."""

from typing import Annotated, Any

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
    deals_board_id: str = ""
    work_orders_board_id: str = ""
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    anthropic_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    anthropic_max_retries: int = Field(default=2, ge=0, le=5)
    anthropic_max_tokens: int = Field(default=700, ge=64, le=4096)
    deterministic_synthesis_fallback: bool = False
    usd_to_inr_rate: str | None = None
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    app_timezone: str = "Asia/Kolkata"
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:3000",
    )
    max_message_length: int = Field(default=4000, ge=1, le=20_000)
    max_history_messages: int = Field(default=20, ge=0, le=100)

    @field_validator("monday_api_token", "anthropic_api_key", mode="before")
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
