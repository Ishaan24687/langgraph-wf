"""Pure business rules. No LLM, no database, no LangGraph - so they are easy to test."""

from datetime import date

TODAY = date(2026, 11, 24)  # pinned so seeded data and lesson output stay stable


def coding_issues(claim: dict, today: date = TODAY) -> list[str]:
    """Problems that would get this claim denied. Empty list means clean."""
    issues = []
    if claim["requires_modifier"] and not claim["modifier"]:
        issues.append(f"code {claim['code']} requires a modifier (CO-4 risk)")
    if claim["charge_amount"] <= 0:
        issues.append("charge_amount must be positive")
    if claim["allowed_amount"] is None:
        issues.append(f"no contracted rate for {claim['code']} with {claim['payer_id']}")
    # Timely filing runs from service date to the date the claim reached the payer.
    # An unsubmitted claim is measured against today, because the clock is still running.
    filed = date.fromisoformat(claim["submit_date"]) if claim["submit_date"] else today
    age_days = (filed - date.fromisoformat(claim["service_date"])).days
    if age_days > claim["timely_filing_days"]:
        issues.append(
            f"service is {age_days} days old, past the "
            f"{claim['timely_filing_days']}-day filing limit (CO-29 risk)"
        )
    return issues


def shortfall(allowed: float | None, paid: float | None) -> float:
    """Dollars still owed on a claim. 0.0 when nothing is outstanding."""
    return round(max((allowed or 0.0) - (paid or 0.0), 0.0), 2)
