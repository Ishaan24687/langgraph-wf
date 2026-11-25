"""Shared plumbing: database handle and chat model. Nothing LangGraph-specific."""

import os
import sqlite3
from pathlib import Path

from langchain_ollama import ChatOllama

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "claims.db"
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")


def db() -> sqlite3.Connection:
    """Read-only-by-convention connection. Rows behave like dicts."""
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} is missing. Run: uv run python db/seed.py")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# To move to Postgres: pip install "psycopg[binary]", then replace the body above with
#   import psycopg; from psycopg.rows import dict_row
#   return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
# and change the ? placeholders in the lessons to %s. Nothing else changes.


def llm(**overrides) -> ChatOllama:
    """Local model via Ollama. temperature=0 keeps lesson output repeatable."""
    # qwen3 emits <think> blocks; other Ollama models reject the think flag entirely.
    kw = {"reasoning": False} if "qwen3" in MODEL else {}
    return ChatOllama(model=MODEL, temperature=0, **kw, **overrides)


CLAIM_SQL = """
SELECT c.claim_id, c.patient_id, c.payer_id, c.code, c.modifier, c.charge_amount,
       c.service_date, c.submit_date, c.status, c.denial_code, c.paid_amount,
       p.name AS payer_name, p.timely_filing_days,
       pc.short_desc, pc.code_system, pc.category, pc.requires_modifier,
       f.allowed_amount
FROM claims c
JOIN payers p            ON p.payer_id = c.payer_id
JOIN procedure_codes pc  ON pc.code = c.code
LEFT JOIN fee_schedule f ON f.code = c.code AND f.payer_id = c.payer_id
WHERE c.claim_id = ?
"""


def load_claim(claim_id: int) -> dict:
    """One claim joined to its payer, code and contracted rate."""
    with db() as con:
        row = con.execute(CLAIM_SQL, (claim_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no claim {claim_id}. Try a claim_id between 1001 and 1500.")
    return dict(row)
