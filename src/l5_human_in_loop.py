"""Lesson 5 - persistence and a human gate.

Two new pieces:
  * a checkpointer saves state after every node, keyed by thread_id
  * interrupt() stops the graph mid-run and hands control back to you

    START -> load -> analyze --not appealable--> END
                        |
                    draft_appeal -> human_review (PAUSE) -> send -> END

Nothing resumes without a checkpointer: that is where the paused state lives.

Run:  uv run python src/l5_human_in_loop.py            # asks you at the terminal
      uv run python src/l5_human_in_loop.py approve    # answers for you
"""

import sys

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from common import db
from l3_branching import CycleState, analyze_denial, draft_appeal, load, route_after_analysis


def human_review(state: CycleState) -> dict:
    """interrupt() raises out of the node. The graph stops here and keeps its state."""
    answer = interrupt({
        "claim_id": state["claim_id"],
        "denial_reason": state["denial_reason"],
        "letter": state["appeal_letter"],
        "instructions": "reply 'approve' to send, or paste replacement text",
    })
    if isinstance(answer, str) and answer.strip().lower() == "approve":
        return {"log": ["reviewer approved the letter"]}
    return {"appeal_letter": str(answer), "log": ["reviewer rewrote the letter"]}


def send(state: CycleState) -> dict:
    # A real system would call the clearinghouse API here. Note that it happens
    # AFTER the human gate, never before.
    return {"attempts": state["attempts"] + 1, "log": ["appeal sent to payer"]}


builder = StateGraph(CycleState)
for node in (load, analyze_denial, draft_appeal, human_review, send):
    builder.add_node(node.__name__, node)

builder.add_edge(START, "load")
builder.add_edge("load", "analyze_denial")
builder.add_conditional_edges("analyze_denial", route_after_analysis, ["draft_appeal", END])
builder.add_edge("draft_appeal", "human_review")
builder.add_edge("human_review", "send")
builder.add_edge("send", END)

# Swap InMemorySaver for SqliteSaver or PostgresSaver and a pause survives a restart.
graph = builder.compile(checkpointer=InMemorySaver())


if __name__ == "__main__":
    canned = sys.argv[1] if len(sys.argv) > 1 else None

    with db() as con:
        claim_id = con.execute(
            "SELECT claim_id FROM claims WHERE status='DENIED' AND denial_code='CO-50' LIMIT 1"
        ).fetchone()[0]

    # thread_id names the conversation. Same id = same saved state.
    config = {"configurable": {"thread_id": f"claim-{claim_id}"}}
    state = graph.invoke({"claim_id": claim_id, "log": [], "attempts": 0}, config)

    while "__interrupt__" in state:
        payload = state["__interrupt__"][0].value
        print(f"\n=== PAUSED on claim {payload['claim_id']} ({payload['denial_reason']})")
        print(payload["letter"])
        print(f"\n{payload['instructions']}")
        answer = canned if canned else input("> ")
        print(f"[resuming with: {answer[:40]!r}]")
        state = graph.invoke(Command(resume=answer), config)  # Command carries your reply in

    print("\n=== finished")
    for line in state["log"]:
        print("  -", line)
    print(f"  attempts={state['attempts']}  status={state['status']}")

    # The saved checkpoint is still queryable after the run.
    snapshot = graph.get_state(config)
    print(f"  checkpoint thread={config['configurable']['thread_id']} "
          f"next={snapshot.next or '(done)'}")

# What to notice:
#   * The pause is a value in the result dict ("__interrupt__"), not an exception you catch.
#   * Command(resume=...) sends your answer back into the node that paused. That node
#     re-runs from its start, so keep side effects out of a node that interrupts.
#   * This is the honest fix for small-model output: review the letter, do not trust it.
