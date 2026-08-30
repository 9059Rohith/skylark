"""Structured data-quality reporting."""

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataQualityReport(BaseModel):
    """Quality accounting attached to every deterministic business metric."""

    model_config = ConfigDict(frozen=True)

    total_rows: int = Field(default=0, ge=0)
    included_rows: int = Field(default=0, ge=0)
    exclusions: dict[str, int] = Field(default_factory=dict)
    normalization_notes: list[str] = Field(default_factory=list)
    duplicate_records: list[tuple[str, str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def included_rows_do_not_exceed_total_rows(self) -> "DataQualityReport":
        if self.included_rows > self.total_rows:
            raise ValueError("included_rows cannot exceed total_rows")
        if any(count < 0 for count in self.exclusions.values()):
            raise ValueError("exclusion counts cannot be negative")
        return self

    def merge(self, *reports: "DataQualityReport") -> "DataQualityReport":
        """Return one report containing the additive accounting from every input report."""
        all_reports = (self, *reports)
        exclusions: Counter[str] = Counter()
        for report in all_reports:
            exclusions.update(report.exclusions)
        return DataQualityReport(
            total_rows=sum(report.total_rows for report in all_reports),
            included_rows=sum(report.included_rows for report in all_reports),
            exclusions=dict(exclusions),
            normalization_notes=[
                note for report in all_reports for note in report.normalization_notes
            ],
            duplicate_records=[
                duplicate
                for report in all_reports
                for duplicate in report.duplicate_records
            ],
        )
