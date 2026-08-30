"""Typed results shared by deterministic intelligence functions."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.cleaning.quality_report import DataQualityReport


class AnalysisResult(BaseModel):
    """Structured arithmetic plus the quality accounting behind it."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    metrics: dict[str, Any] = Field(default_factory=dict)
    quality: DataQualityReport
