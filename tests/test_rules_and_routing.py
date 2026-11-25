"""Covers the two bits of real logic: the coding rules and the graph's routing."""

from datetime import date

import pytest
from langgraph.graph import END

import rules
from l3_branching import MAX_ATTEMPTS, route_after_adjudication, route_after_analysis

TODAY = date(2026, 11, 24)


def claim(**overrides) -> dict:
    base = {
        "code": "80002", "modifier": None, "requires_modifier": 0,
        "charge_amount": 200.0, "allowed_amount": 132.0,
        "service_date": "2026-11-01", "submit_date": "2026-11-10",
        "payer_id": "BCBS", "timely_filing_days": 180,
    }
    return base | overrides


def test_clean_claim_has_no_issues():
    assert rules.coding_issues(claim(), TODAY) == []


def test_missing_modifier_is_flagged():
    issues = rules.coding_issues(claim(requires_modifier=1), TODAY)
    assert any("modifier" in i for i in issues)


def test_modifier_present_passes():
    assert rules.coding_issues(claim(requires_modifier=1, modifier="26"), TODAY) == []


def test_timely_filing_measured_from_submit_date_not_today():
    # Filed 9 days after service, so this is timely even though the service is old.
    old = claim(service_date="2025-01-01", submit_date="2025-01-10")
    assert rules.coding_issues(old, TODAY) == []
    late = claim(service_date="2025-01-01", submit_date="2026-01-10")
    assert any("filing limit" in i for i in rules.coding_issues(late, TODAY))


def test_unsubmitted_claim_clock_runs_to_today():
    assert any("filing limit" in i
               for i in rules.coding_issues(
                   claim(service_date="2025-01-01", submit_date=None), TODAY))


def test_missing_contracted_rate_is_flagged():
    assert any("contracted rate" in i
               for i in rules.coding_issues(claim(allowed_amount=None), TODAY))


@pytest.mark.parametrize("allowed,paid,expected", [
    (132.0, 132.0, 0.0),
    (132.0, None, 132.0),
    (132.0, 200.0, 0.0),   # overpayment is not negative money owed
    (None, None, 0.0),
    (132.0, 60.0, 72.0),
])
def test_shortfall(allowed, paid, expected):
    assert rules.shortfall(allowed, paid) == expected


def test_paid_claim_exits_the_graph():
    assert route_after_adjudication({"status": "PAID", "attempts": 0}) == END


def test_denial_goes_to_analysis():
    assert route_after_adjudication({"status": "DENIED", "attempts": 0}) == "analyze_denial"


def test_appeal_loop_stops_at_the_cap():
    # Guards against an infinite appeal cycle.
    assert route_after_adjudication(
        {"status": "DENIED", "attempts": MAX_ATTEMPTS}) == END


def test_unappealable_denial_skips_the_llm():
    assert route_after_analysis({"appealable": False}) == END
    assert route_after_analysis({"appealable": True}) == "draft_appeal"
