"""Lesson 2 - your first StateGraph. Three nodes in a line, zero LLM calls.

Point of this lesson: a graph is just functions plus wiring. AI is optional.

    START -> load -> check_coding -> price -> END

Run:  uv run python src/l2_linear_graph.py
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

import rules
from common import load_claim


class ClaimState(TypedDict):
    """The one dict every node reads from and writes to.

    Plain keys are overwritten by whichever node returns them.
    `Annotated[list, operator.add]` is a *reducer*: returned lists get appended
    instead of replacing what is already there.
    """
    claim_id: int
    claim: dict
    issues: Annotated[list[str], operator.add]
    allowed: float
    shortfall: float
    decision: str


# --- nodes: (state) -> partial state update ----------------------------------

def load(state: ClaimState) -> dict:
    return {"claim": load_claim(state["claim_id"])}


def check_coding(state: ClaimState) -> dict:
    # returned list is APPENDED to state["issues"] because of the reducer
    return {"issues": rules.coding_issues(state["claim"])}


def price(state: ClaimState) -> dict:
    claim = state["claim"]
    allowed = claim["allowed_amount"] or 0.0
    gap = rules.shortfall(allowed, claim["paid_amount"])
    decision = "hold for correction" if state["issues"] else (
        "collected in full" if gap == 0 else f"chase ${gap:.2f}"
    )
    return {"allowed": allowed, "shortfall": gap, "decision": decision}


# --- wiring ------------------------------------------------------------------

builder = StateGraph(ClaimState)
builder.add_node("load", load)
builder.add_node("check_coding", check_coding)
builder.add_node("price", price)

builder.add_edge(START, "load")
builder.add_edge("load", "check_coding")
builder.add_edge("check_coding", "price")
builder.add_edge("price", END)

graph = builder.compile()  # compile() validates the wiring and returns a runnable


if __name__ == "__main__":
    print(graph.get_graph().draw_mermaid())  # paste into mermaid.live to see it

    for claim_id in (1001, 1004, 1007):
        final = graph.invoke({"claim_id": claim_id, "issues": []})
        claim = final["claim"]
        print(f"\nclaim {claim_id}  {claim['code']} -> {claim['payer_id']}  status={claim['status']}")
        print(f"  charge ${claim['charge_amount']:.2f} | allowed ${final['allowed']:.2f} "
              f"| outstanding ${final['shortfall']:.2f}")
        print(f"  issues: {final['issues'] or 'none'}")
        print(f"  decision: {final['decision']}")

# What to notice:
#   * `invoke` returns the FINAL state, not just the last node's return value.
#   * Nodes never mutate state in place; they return the keys they changed.
#   * Swap any node for an LLM call and nothing else in this file changes.
