"""Shared, conservative deal lifecycle classification."""

from app.cleaning.normalizer import normalize_stage
from app.intelligence.records import Record, record_value, text_value


ACTIVE_PIPELINE_STAGES = frozenset(
    {"Open", "On Hold", "Lead", "Qualified", "Proposal", "Negotiation"}
)


def classify_deal_lifecycle(deal: Record) -> str:
    """Return active, closed_won, closed_lost, or unknown.

    Terminal signals take precedence because real boards can contain a stale broad
    Deal Status beside a later detailed funnel stage.
    """
    normalized = [
        normalize_stage(raw).value
        for raw in (
            record_value(deal, "deal_status"),
            record_value(deal, "stage", "status", "deal_stage"),
        )
        if text_value(raw) is not None
    ]
    if "Won" in normalized:
        return "closed_won"
    if "Lost" in normalized:
        return "closed_lost"
    if any(stage in ACTIVE_PIPELINE_STAGES for stage in normalized):
        return "active"
    return "unknown"
