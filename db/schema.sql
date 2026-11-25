-- Reimbursement-cycle sandbox schema.
-- All data is synthetic. Code descriptors are paraphrases written for this repo,
-- not official AMA CPT text. See README "Data and licensing".

DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS fee_schedule;
DROP TABLE IF EXISTS denial_codes;
DROP TABLE IF EXISTS payers;
DROP TABLE IF EXISTS procedure_codes;

CREATE TABLE procedure_codes (
    code              TEXT PRIMARY KEY,
    code_system       TEXT NOT NULL,            -- 'HCPCS' (public domain) or 'CPT-SYNTHETIC'
    short_desc        TEXT NOT NULL,
    category          TEXT NOT NULL,
    requires_modifier INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE payers (
    payer_id           TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    timely_filing_days INTEGER NOT NULL
);

CREATE TABLE fee_schedule (
    code           TEXT NOT NULL REFERENCES procedure_codes(code),
    payer_id       TEXT NOT NULL REFERENCES payers(payer_id),
    allowed_amount REAL NOT NULL,
    PRIMARY KEY (code, payer_id)
);

-- Claim Adjustment Reason Codes (CARC). Publicly published by X12.
CREATE TABLE denial_codes (
    code       TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,
    appealable INTEGER NOT NULL
);

CREATE TABLE claims (
    claim_id      INTEGER PRIMARY KEY,
    patient_id    TEXT NOT NULL,
    payer_id      TEXT NOT NULL REFERENCES payers(payer_id),
    code          TEXT NOT NULL REFERENCES procedure_codes(code),
    modifier      TEXT,
    charge_amount REAL NOT NULL,
    service_date  TEXT NOT NULL,
    submit_date   TEXT,
    status        TEXT NOT NULL,                -- NEW | PAID | UNDERPAID | DENIED
    denial_code   TEXT REFERENCES denial_codes(code),
    paid_amount   REAL
);

CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_code   ON claims(code);
