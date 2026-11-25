"""Build db/claims.db and fill it with synthetic reimbursement data.

Run:  uv run python db/seed.py
Idempotent: drops and recreates every table.
"""

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "claims.db"

# HCPCS Level II codes are public domain (published by CMS). Descriptors below are
# short paraphrases written for this repo. The 8xxxx codes are invented placeholders
# that sit where licensed CPT codes would go in a real system.
PROCEDURE_CODES = [
    ("G0008", "HCPCS", "Flu vaccine administration", "immunization", 0),
    ("G0439", "HCPCS", "Annual wellness visit, subsequent", "preventive", 0),
    ("J1100", "HCPCS", "Dexamethasone sodium phosphate injection, 1 mg", "drug", 0),
    ("J3301", "HCPCS", "Triamcinolone acetonide injection, 10 mg", "drug", 0),
    ("A4253", "HCPCS", "Blood glucose test strips, box of 50", "supply", 0),
    ("A4259", "HCPCS", "Lancets, box of 100", "supply", 0),
    ("E0601", "HCPCS", "CPAP device", "equipment", 1),
    ("L3908", "HCPCS", "Wrist hand orthosis, prefabricated", "equipment", 1),
    ("80001", "CPT-SYNTHETIC", "Office visit, established patient, low complexity", "office-visit", 0),
    ("80002", "CPT-SYNTHETIC", "Office visit, established patient, moderate complexity", "office-visit", 0),
    ("80003", "CPT-SYNTHETIC", "Diagnostic imaging, single view", "imaging", 1),
    ("80004", "CPT-SYNTHETIC", "Minor surgical procedure, outpatient", "surgery", 1),
]

PAYERS = [
    ("MCR", "Medicare (synthetic)", 365),
    ("BCBS", "Blue Cross Blue Shield (synthetic)", 180),
    ("AETNA", "Aetna (synthetic)", 120),
    ("UHC", "UnitedHealthcare (synthetic)", 90),
]

# CARC codes are published publicly by X12.
DENIAL_CODES = [
    ("CO-16", "Claim lacks information needed for adjudication", 1),
    ("CO-29", "Time limit for filing has expired", 0),
    ("CO-50", "Not deemed medically necessary by the payer", 1),
    ("CO-97", "Service is bundled into another paid service", 1),
    ("CO-4", "Procedure code requires a modifier that is missing or invalid", 1),
]

# Base allowed amount per code; each payer pays a fixed multiple of it.
BASE_ALLOWED = {
    "G0008": 25.0, "G0439": 118.0, "J1100": 6.0, "J3301": 14.0,
    "A4253": 32.0, "A4259": 11.0, "E0601": 820.0, "L3908": 240.0,
    "80001": 74.0, "80002": 132.0, "80003": 58.0, "80004": 410.0,
}
PAYER_FACTOR = {"MCR": 1.00, "BCBS": 1.22, "AETNA": 1.15, "UHC": 0.93}


def seed(db_path: Path = DB_PATH, n_claims: int = 500, seed_value: int = 7) -> None:
    rng = random.Random(seed_value)  # fixed seed so lessons give repeatable output
    con = sqlite3.connect(db_path)
    con.executescript((HERE / "schema.sql").read_text())

    con.executemany("INSERT INTO procedure_codes VALUES (?,?,?,?,?)", PROCEDURE_CODES)
    con.executemany("INSERT INTO payers VALUES (?,?,?)", PAYERS)
    con.executemany("INSERT INTO denial_codes VALUES (?,?,?)", DENIAL_CODES)
    con.executemany(
        "INSERT INTO fee_schedule VALUES (?,?,?)",
        [
            (code, payer, round(BASE_ALLOWED[code] * PAYER_FACTOR[payer], 2))
            for code in BASE_ALLOWED
            for payer in PAYER_FACTOR
        ],
    )

    codes = [c[0] for c in PROCEDURE_CODES]
    needs_mod = {c[0] for c in PROCEDURE_CODES if c[4]}
    payer_ids = [p[0] for p in PAYERS]
    today = date(2026, 11, 24)
    rows = []

    for claim_id in range(1001, 1001 + n_claims):
        code = rng.choice(codes)
        payer = rng.choice(payer_ids)
        allowed = round(BASE_ALLOWED[code] * PAYER_FACTOR[payer], 2)
        charge = round(allowed * rng.uniform(1.4, 2.6), 2)  # clinics charge above allowed
        age_days = rng.randint(1, 420)
        service_date = today - timedelta(days=age_days)

        # 15% of modifier-requiring codes are submitted without one -> CO-4 denial.
        modifier = None
        if code in needs_mod and rng.random() > 0.15:
            modifier = rng.choice(["26", "TC", "59", "LT", "RT"])

        roll = rng.random()
        if roll < 0.12:
            status, denial, paid, submit = "NEW", None, None, None
        elif code in needs_mod and modifier is None:
            status, denial, paid = "DENIED", "CO-4", 0.0
            submit = service_date + timedelta(days=rng.randint(1, 20))
        elif age_days > 365:
            status, denial, paid = "DENIED", "CO-29", 0.0
            submit = service_date + timedelta(days=rng.randint(370, 400))
        elif roll < 0.32:
            status, denial = "DENIED", rng.choice(["CO-16", "CO-50", "CO-97"])
            paid = 0.0
            submit = service_date + timedelta(days=rng.randint(1, 30))
        elif roll < 0.47:
            status, denial = "UNDERPAID", None
            paid = round(allowed * rng.uniform(0.45, 0.9), 2)
            submit = service_date + timedelta(days=rng.randint(1, 30))
        else:
            status, denial, paid = "PAID", None, allowed
            submit = service_date + timedelta(days=rng.randint(1, 30))

        rows.append((
            claim_id, f"P{rng.randint(1, 120):04d}", payer, code, modifier,
            charge, service_date.isoformat(),
            submit.isoformat() if submit else None,
            status, denial, paid,
        ))

    con.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()

    counts = dict(con.execute("SELECT status, count(*) FROM claims GROUP BY status").fetchall())
    con.close()
    print(f"seeded {db_path}")
    print(f"  procedure_codes={len(PROCEDURE_CODES)} payers={len(PAYERS)} claims={n_claims}")
    print(f"  by status: {counts}")
    assert sum(counts.values()) == n_claims, "claim rows lost on insert"
    assert set(counts) <= {"NEW", "PAID", "UNDERPAID", "DENIED"}, f"bad status in {counts}"


if __name__ == "__main__":
    seed()
    sys.exit(0)
