from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.routing import Intent, parse_intent, resolve_period, resolve_quarter


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("How healthy is our pipeline this quarter?", Intent.PIPELINE_HEALTH),
        ("Which won deals have no work orders?", Intent.WON_WITHOUT_WORK_ORDERS),
        ("What is average work order completion time?", Intent.WORK_ORDER_COMPLETION),
        ("How many deals are missing close dates?", Intent.DATA_QUALITY),
        ("Draft the weekly leadership update", Intent.LEADERSHIP_UPDATE),
    ],
)
def test_required_query_archetypes_have_explicit_routes(
    message: str, expected: Intent
) -> None:
    """Removing an explicit archetype route sends a supported question elsewhere."""
    decision = parse_intent(message)

    assert decision.intent == expected
    assert decision.clarification_question is None


def test_follow_up_sector_breakdown_reuses_prior_intent_and_scope() -> None:
    """Losing persisted context makes a natural follow-up impossible to answer."""
    prior = parse_intent("How healthy is our pipeline this quarter?")

    follow_up = parse_intent(
        "Break that down by sector", prior_intent=prior.intent, prior_period=prior.period
    )

    assert follow_up.intent == Intent.PIPELINE_HEALTH
    assert follow_up.breakdown_by_sector is True
    assert follow_up.period == prior.period
    assert follow_up.clarification_question is None


def test_multiple_sector_scopes_produce_exactly_one_targeted_clarification() -> None:
    """Guessing between two sectors would silently answer the wrong scope."""
    decision = parse_intent("Show pipeline for healthcare or energy")

    assert decision.intent == Intent.PIPELINE_HEALTH
    assert decision.clarification_question == (
        "Which sector should I use: Healthcare or Energy?"
    )


def test_configured_fiscal_quarter_is_resolved_from_injected_clock() -> None:
    """Using wall-clock or calendar quarters breaks reproducible fiscal scope."""
    period = resolve_quarter(
        "this quarter",
        now=datetime(2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        fiscal_year_start_month=4,
    )

    assert period is not None
    assert period.start.isoformat() == "2026-07-01"
    assert period.end.isoformat() == "2026-09-30"
    assert period.label == "FY2026 Q2"


def test_fiscal_quarter_resolves_across_calendar_year_boundary() -> None:
    """Fiscal Q4 in January must remain in the fiscal year that began last April."""
    period = resolve_quarter(
        "current quarter",
        now=datetime(2027, 1, 15, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        fiscal_year_start_month=4,
    )

    assert period is not None
    assert period.start.isoformat() == "2027-01-01"
    assert period.end.isoformat() == "2027-03-31"
    assert period.label == "FY2026 Q4"


def test_genuinely_unresolved_business_scope_asks_one_targeted_question() -> None:
    """Defaulting a vague question to pipeline health invents caller intent."""
    decision = parse_intent("How are things looking?")

    assert decision.clarification_question == (
        "Which view do you need: pipeline health, won deals without work orders, "
        "work-order completion, data quality, or a leadership update?"
    )


def test_this_month_resolves_deterministically_from_injected_clock() -> None:
    """Month scope must not depend on when or where the test process runs."""
    period = resolve_period(
        "this month",
        now=datetime(2026, 8, 30, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        fiscal_year_start_month=4,
    )

    assert period is not None
    assert period.start.isoformat() == "2026-08-01"
    assert period.end.isoformat() == "2026-08-31"
    assert period.label == "August 2026"
