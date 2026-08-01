"""NationLabs Presales Orchestrator — SQLite schema & migrations.

Source of truth: NationLabs AI Presales Orchestrator spec (docx §4, §24, §25).
All tables are created idempotently. audit_log is append-only by convention —
no UPDATE/DELETE statements exist anywhere in the codebase for it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- §4 Opportunity Creation: NL-OPP-YYYY-XXXX, everything links back here
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL UNIQUE,              -- NL-OPP-2026-0001
    status TEXT NOT NULL DEFAULT 'New Intake',
    customer_org TEXT,
    end_user_org TEXT,
    requirement_title TEXT,
    opportunity_owner TEXT,
    technical_owner TEXT,
    commercial_owner TEXT,
    priority TEXT DEFAULT 'NORMAL',
    source_channel TEXT,                      -- whatsapp_paste | screenshot | file | verbal | manual
    source_raw_path TEXT,                     -- original preserved unmodified (§3)
    submission_deadline TEXT,
    delivery_deadline TEXT,
    extraction_json TEXT,                     -- AI interpretation, stored separately (§3)
    classification_json TEXT,                 -- §6 multi-label classification + confidence
    readiness_score INTEGER,                  -- §7 0-100
    readiness_level TEXT,                     -- READY | READY_WITH_ASSUMPTIONS | CLARIFICATION_REQUIRED
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- §8 Clarification Management
CREATE TABLE IF NOT EXISTS clarifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL REFERENCES opportunities(opp_id),
    question TEXT NOT NULL,
    answer TEXT,
    is_critical INTEGER NOT NULL DEFAULT 1,
    asked_at TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT,
    UNIQUE(opp_id, question)                  -- "do not repeatedly ask the same question"
);

-- §10 Vendor & Supplier Contact Register (runtime mirror of Excel master)
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_name TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('OEM','DISTRIBUTOR','RESELLER','SUPPLIER')),
    tech_domains TEXT NOT NULL,               -- JSON array of §6.6 domains
    product_family TEXT,
    contact_name TEXT,
    job_title TEXT,
    email TEXT NOT NULL,
    email_domain TEXT,
    phone TEXT,
    country TEXT DEFAULT 'UAE',
    vendor_authorised INTEGER NOT NULL DEFAULT 0,
    deal_reg_capable INTEGER NOT NULL DEFAULT 0,
    role TEXT DEFAULT 'SALES',                -- ACCOUNT_MANAGER|SALES|PRESALES|DEAL_REG|ESCALATION
    assigned_nl_owner TEXT,
    contact_status TEXT NOT NULL DEFAULT 'Unverified'
        CHECK (contact_status IN ('Verified','Unverified','Expired','Inactive','Duplicate','Missing','Under validation')),
    last_validated TEXT,
    UNIQUE(vendor_name, email)
);

-- §18 Technology Ownership Matrix
CREATE TABLE IF NOT EXISTS ownership_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tech_domain TEXT NOT NULL,
    oem TEXT,
    product_family TEXT,
    primary_owner TEXT NOT NULL,
    backup_owner TEXT,
    commercial_owner TEXT,
    technical_reviewer TEXT,
    escalation_manager TEXT,
    UNIQUE(tech_domain, oem, product_family)
);

-- §12/§14 RFQs — external comms require approval
CREATE TABLE IF NOT EXISTS rfqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL REFERENCES opportunities(opp_id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    rfq_ref TEXT NOT NULL UNIQUE,             -- NL-RFQ-2026-0001
    draft_path TEXT,                          -- file in outbox/vendor_emails/
    disclose_end_user INTEGER NOT NULL DEFAULT 0,   -- §11 policy-engine output
    disclosure_approved_by TEXT,
    disclosure_approved_at TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFTED'
        CHECK (status IN ('DRAFTED','AWAITING_APPROVAL','APPROVED','SENT','CANCELLED')),
    approved_by TEXT,
    approved_at TEXT,
    sent_at TEXT,                             -- set by human dispatch confirmation
    response_deadline TEXT,
    auto_followup_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- §15 Follow-Up Management
CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfq_id INTEGER NOT NULL REFERENCES rfqs(id),
    followup_n INTEGER NOT NULL,              -- 1,2,3 then escalation
    scheduled_at TEXT NOT NULL,
    sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','SENT','STOPPED','ESCALATED')),
    stop_reason TEXT,
    UNIQUE(rfq_id, followup_n)
);

-- §16 Vendor Response Analysis
CREATE TABLE IF NOT EXISTS vendor_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfq_id INTEGER NOT NULL REFERENCES rfqs(id),
    raw_path TEXT,                            -- original preserved
    response_type TEXT,                       -- 19 types per §16
    parsed_json TEXT,                         -- extracted fields
    alert_path TEXT,                          -- internal alert file (§17)
    received_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- §19 Quotation Completion Gate
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL REFERENCES opportunities(opp_id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    response_id INTEGER REFERENCES vendor_responses(id),
    quote_ref TEXT,
    quote_date TEXT,
    quote_expiry TEXT,
    currency TEXT DEFAULT 'AED',
    total_before_vat REAL,
    vat_amount REAL,
    total_after_vat REAL,
    extracted_json TEXT,                      -- line items, terms (§16 extraction list)
    comparison_json TEXT,                     -- quote-vs-RFQ diff (§16)
    status TEXT NOT NULL DEFAULT 'Incomplete'
        CHECK (status IN ('Complete','Complete with assumptions','Incomplete',
                          'Awaiting clarification','Rejected','Superseded','Expired')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- §21 Costing Validation — every check individually recorded
CREATE TABLE IF NOT EXISTS costing_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL REFERENCES quotes(id),
    check_name TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('PASS','WARN','FAIL')),
    expected_value TEXT,
    actual_value TEXT,
    evidence_source TEXT,
    confidence REAL,
    recommended_correction TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- §13 Deal Registration Workflow
CREATE TABLE IF NOT EXISTS deal_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL REFERENCES opportunities(opp_id),
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    status TEXT NOT NULL DEFAULT 'Not submitted'
        CHECK (status IN ('Not required','Not submitted','Drafted','Awaiting approval',
                          'Submitted','Pending','Additional information required',
                          'Approved','Rejected','Conflict detected','Expired','Cancelled')),
    reg_reference TEXT,
    reg_validity TEXT,
    price_protection_validity TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(opp_id, vendor_id)
);

-- §22 Approval Routing (all kinds, incl. §11 disclosure approvals)
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT NOT NULL REFERENCES opportunities(opp_id),
    kind TEXT NOT NULL CHECK (kind IN ('RFQ_FIRST_SEND','END_USER_DISCLOSURE','FINANCE',
                                       'FINAL_VERIFICATION','ASSUMPTIONS_OVERRIDE','CUSTOMER_SUBMISSION')),
    request_path TEXT,                        -- file in outbox/approval_requests/
    requested_from TEXT,                      -- role or person
    decision TEXT CHECK (decision IN ('APPROVED','REJECTED','RETURNED')),
    decided_by TEXT,
    decided_at TEXT,
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- §25 Audit & Traceability — APPEND ONLY
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id TEXT,
    actor TEXT NOT NULL,                      -- user name or 'system' or model name
    component TEXT NOT NULL,                  -- service/module
    action TEXT NOT NULL,
    previous_value TEXT,
    new_value TEXT,
    reason TEXT,
    source TEXT,
    confidence REAL,
    approval_ref INTEGER,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_opp ON audit_log(opp_id);
CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_rfq_opp ON rfqs(opp_id);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, scheduled_at);
"""


def get_db(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_db(db_path)
    with conn:
        conn.executescript(DDL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    conn.close()


if __name__ == "__main__":
    import sys
    init_db(sys.argv[1] if len(sys.argv) > 1 else "nationlabs_runtime/db/orchestrator.db")
    print("DB initialised.")
