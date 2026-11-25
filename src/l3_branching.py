"""Lesson 3 - conditional edges and a loop. This is the shape LangGraph exists for.

The reimbursement cycle, as a graph:

    START -> load -> adjudicate ---PAID--------------------> END
                          ^            |
                          |         DENIED / UNDERPAID
                          |            v
                     resubmit <- draft_appeal <- analyze --not appealable--> END

Run:  uv run python src/l3_branching.py
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from common import db, llm, load_claim

MAX_ATTEMPTS = 2  # without a cap, an appeal loop runs until recursion_limit kills it


class CycleState(TypedDict):
    claim_id: int
    claim: dict
    status: str
    denial_code: str | None
    denial_reason: str | None
    appealable: bool
    attempts: int
    appeal_letter: str | None
    log: Annotated[list[str], operator.add]


def load(state: CycleState) -> dict:
    claim = load_claim(state["claim_id"])
    return {
        "claim": claim,
        "status": claim["status"],
        "denial_code": claim["denial_code"],
        "attempts": 0,
        "log": [f"loaded claim {claim['claim_id']} ({claim['code']} -> {claim['payer_id']})"],
    }


def adjudicate(state: CycleState) -> dict:
    """Stand-in for the payer. First pass replays the stored remittance;
    later passes decide the appeal."""
    if state["attempts"] == 0:
        return {"log": [f"payer responded: {state['status']} {state['denial_code'] or ''}".strip()]}
    # An appealable denial that went back with a corrected letter gets paid.
    if state["appealable"]:
        return {"status": "PAID", "denial_code": None, "log": ["appeal accepted, claim paid"]}
    return {"log": ["appeal rejected, denial stands"]}


def analyze_denial(state: CycleState) -> dict:
    """Database lookup, not an LLM. Cheaper and always right."""
    if state["denial_code"] is None:  # UNDERPAID claims carry no CARC code
        return {"denial_reason": "paid below the contracted rate", "appealable": True,
                "log": ["underpayment: contracted rate not honoured"]}
    with db() as con:
        row = con.execute(
            "SELECT reason, appealable FROM denial_codes WHERE code = ?", (state["denial_code"],)
        ).fetchone()
    reason = row["reason"] if row else "unknown denial code"
    appealable = bool(row["appealable"]) if row else False
    return {"denial_reason": reason, "appealable": appealable,
            "log": [f"{state['denial_code']}: {reason} (appealable={appealable})"]}


def draft_appeal(state: CycleState) -> dict:
    """The only LLM node in this graph. Everything deterministic stayed deterministic."""
    claim = state["claim"]
    msg = llm(num_predict=260).invoke([
        ("system", "You write short, factual medical-claim appeal letters. "
                   "Max 120 words. No invented clinical facts. No placeholders."),
        ("human", f"Payer {claim['payer_name']} denied claim {claim['claim_id']} for "
                  f"{claim['code']} ({claim['short_desc']}), date of service "
                  f"{claim['service_date']}, charge ${claim['charge_amount']:.2f}, "
                  f"contracted rate ${claim['allowed_amount']}. "
                  f"Denial reason: {state['denial_reason']}. Write the appeal."),
    ])
    return {"appeal_letter": msg.content.strip(), "log": ["appeal letter drafted"]}


def resubmit(state: CycleState) -> dict:
    return {"attempts": state["attempts"] + 1, "log": ["resubmitted to payer"]}


# --- routing: a function that returns the NAME of the next node ---------------

def route_after_adjudication(state: CycleState) -> str:
    if state["status"] == "PAID":
        return END
    if state["attempts"] >= MAX_ATTEMPTS:
        return END  # stop chasing; a human takes it from here
    return "analyze_denial"


def route_after_analysis(state: CycleState) -> str:
    return "draft_appeal" if state["appealable"] else END


builder = StateGraph(CycleState)
for node in (load, adjudicate, analyze_denial, draft_appeal, resubmit):
    builder.add_node(node.__name__, node)

builder.add_edge(START, "load")
builder.add_edge("load", "adjudicate")
builder.add_conditional_edges("adjudicate", route_after_adjudication,
                              ["analyze_denial", END])
builder.add_conditional_edges("analyze_denial", route_after_analysis,
                              ["draft_appeal", END])
builder.add_edge("draft_appeal", "resubmit")
builder.add_edge("resubmit", "adjudicate")  # <- the cycle a plain chain cannot express

graph = builder.compile()


if __name__ == "__main__":
    import sys

    with db() as con:
        ids = [r[0] for r in con.execute(
            "SELECT claim_id FROM claims WHERE status='DENIED' AND denial_code IN ('CO-16','CO-29')"
            " ORDER BY denial_code LIMIT 2").fetchall()]
    ids = [int(a) for a in sys.argv[1:]] or ids

    for claim_id in ids:
        final = graph.invoke({"claim_id": claim_id, "log": [], "attempts": 0})
        print(f"\n=== claim {claim_id}: ended {final['status']} after {final['attempts']} appeal(s)")
        for line in final["log"]:
            print("  -", line)
        if final.get("appeal_letter"):
            print("  --- letter ---")
            print("  " + final["appeal_letter"].replace("\n", "\n  "))

# What to notice:
#   * `add_conditional_edges` takes a function, not a condition. It returns a node name.
#   * The third argument lists the possible destinations - only for the diagram.
#   * CO-29 (timely filing) is not appealable, so that claim exits before the LLM runs.
#     Routing saved a model call. That is the normal reason to branch.
