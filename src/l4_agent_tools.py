"""Lesson 4 - tools and an agent.

An agent is not a special object. It is this loop, prebuilt for you:

    START -> model --wants a tool?--> tools -> model -> ... --no--> END

You write plain Python functions and decorate them with @tool. The model only
sees each function's name, arguments and docstring, so the docstring IS the API.

Run:  uv run python src/l4_agent_tools.py "which payer denies the most claims?"
"""

import sys

from langchain.agents import create_agent
from langchain_core.tools import tool

from common import db, llm


@tool
def lookup_code(code: str) -> str:
    """Describe one procedure code. Use when asked what a code means.
    Args: code - a procedure code such as 'E0601' or '80002'."""
    with db() as con:
        row = con.execute(
            "SELECT code, code_system, short_desc, category, requires_modifier"
            " FROM procedure_codes WHERE code = ?", (code.strip().upper(),)).fetchone()
    if row is None:
        return f"No code {code} in this database."
    return (f"{row['code']} ({row['code_system']}): {row['short_desc']}; "
            f"category {row['category']}; modifier required: {bool(row['requires_modifier'])}")


@tool
def contracted_rate(code: str, payer_id: str) -> str:
    """Contracted allowed amount for one code with one payer.
    Args: code - procedure code; payer_id - one of MCR, BCBS, AETNA, UHC."""
    with db() as con:
        row = con.execute(
            "SELECT allowed_amount FROM fee_schedule WHERE code = ? AND payer_id = ?",
            (code.strip().upper(), payer_id.strip().upper())).fetchone()
    if row is None:
        return f"No contracted rate for {code} with {payer_id}."
    return f"{payer_id} allows ${row['allowed_amount']:.2f} for {code}."


@tool
def denial_summary(payer_id: str = "") -> str:
    """Count denials grouped by denial code. Use for 'why are claims denied' questions.
    Args: payer_id - optional payer filter (MCR, BCBS, AETNA, UHC); empty means all payers."""
    sql = ("SELECT c.denial_code, d.reason, count(*) AS n FROM claims c"
           " JOIN denial_codes d ON d.code = c.denial_code WHERE c.status = 'DENIED'")
    params: tuple = ()
    if payer_id.strip():
        sql += " AND c.payer_id = ?"
        params = (payer_id.strip().upper(),)
    sql += " GROUP BY c.denial_code ORDER BY n DESC"
    with db() as con:
        rows = con.execute(sql, params).fetchall()
    if not rows:
        return f"No denials found for {payer_id or 'any payer'}."
    return "\n".join(f"{r['denial_code']} x{r['n']}: {r['reason']}" for r in rows)


@tool
def money_outstanding(status: str = "") -> str:
    """Total dollars still owed, by payer. Use for revenue and aging questions.
    Args: status - optional claim status filter (NEW, PAID, UNDERPAID, DENIED); empty means all."""
    sql = ("SELECT c.payer_id, count(*) AS n,"
           " round(sum(max(coalesce(f.allowed_amount,0) - coalesce(c.paid_amount,0), 0)), 2) AS owed"
           " FROM claims c LEFT JOIN fee_schedule f"
           " ON f.code = c.code AND f.payer_id = c.payer_id")
    params: tuple = ()
    if status.strip():
        sql += " WHERE c.status = ?"
        params = (status.strip().upper(),)
    sql += " GROUP BY c.payer_id ORDER BY owed DESC"
    with db() as con:
        rows = con.execute(sql, params).fetchall()
    return "\n".join(f"{r['payer_id']}: ${r['owed']:.2f} outstanding across {r['n']} claims"
                     for r in rows)


TOOLS = [lookup_code, contracted_rate, denial_summary, money_outstanding]

# Every tool above uses ? placeholders with bound parameters and a fixed query shape.
# Never hand a model a tool that executes a SQL string it wrote - that is an injection
# hole and a way to drop your tables.

agent = create_agent(
    model=llm(),
    tools=TOOLS,
    system_prompt=(
        "You are a revenue-cycle analyst for a clinic. Answer only from tool results. "
        "Call a tool before stating any number. If no tool can answer, say so. Be brief."
    ),
)


def ask(question: str) -> str:
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    return result["messages"][-1].content


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "What is code E0601, and what does Medicare allow for it?"
    print(f"Q: {question}\n")
    print(ask(question))

# What to notice:
#   * create_agent replaced langgraph.prebuilt.create_react_agent in LangChain 1.0,
#     and the old `prompt=` argument is now `system_prompt=`.
#   * `result["messages"]` holds the whole transcript: your question, the tool calls,
#     the tool outputs, the final answer. Print it all when a tool is not firing.
#   * Small local models skip tools or mangle arguments. If that happens, try
#     OLLAMA_MODEL=qwen3:4b, or a bigger model.
