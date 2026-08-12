"""P1-11 — Approval engine (config-driven matrix; approved decision #10).

Rules live in approval_rules TABLE — no threshold is a code constant. When
Worksheet AM-1 is signed by Niren/Finance, flip source to 'SIGNED-AM1' with a
plain UPDATE. Provisional seed per original brief: >200K -> Finance; below ->
final verifier; 60K-200K band marked TBC (routes to verifier until AM-1).
"""
import psycopg
from db import PG_DSN, audit

SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_rules (
    rule_id     TEXT PRIMARY KEY,       -- AM-R1..
    min_aed     NUMERIC(14,2) NOT NULL,
    max_aed     NUMERIC(14,2),          -- NULL = no upper bound
    approver_role TEXT NOT NULL,
    sla_hours   INT,
    source      TEXT NOT NULL,          -- PROVISIONAL-* or SIGNED-AM1
    notes       TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id          BIGSERIAL PRIMARY KEY,
    opp_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- PROPOSAL_VALUE/END_USER_DISCLOSURE/COSTING_OVERRIDE
    amount_aed  NUMERIC(14,2),
    routed_to_role TEXT NOT NULL,
    rule_id     TEXT REFERENCES approval_rules(rule_id),
    status      TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING/APPROVED/REJECTED
    decided_by  TEXT,
    decided_at  TIMESTAMPTZ,
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Provisional matrix (Phase 0 Worksheet AM-1, pending Niren/Finance sign-off)
SEED_RULES = [
    ("AM-R1", 0, 60000, "FINAL_VERIFIER", 24,
     "PROVISIONAL-A-5.2-pending", "< 60K: assigned final verifier"),
    ("AM-R2", 60000, 200000, "FINAL_VERIFIER", 24,
     "PROVISIONAL-A-5.2-pending", "60K-200K band TBC — routes to verifier until AM-1 signed"),
    ("AM-R3", 200000, None, "FINANCE", 48,
     "PROVISIONAL-brief-2026-07", "> 200K: Finance/Accounts (from original brief)"),
]


def init_approvals(conn):
    conn.execute(SCHEMA)
    for r in SEED_RULES:
        conn.execute(
            "INSERT INTO approval_rules (rule_id, min_aed, max_aed, approver_role, sla_hours, source, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (rule_id) DO NOTHING", r)
    conn.commit()


def route_amount(conn, amount_aed: float):
    return conn.execute(
        "SELECT rule_id, approver_role, sla_hours FROM approval_rules "
        "WHERE min_aed <= %s AND (max_aed IS NULL OR %s < max_aed) ORDER BY min_aed DESC LIMIT 1",
        (amount_aed, amount_aed)).fetchone()


def evaluate(opp_id: str, amount_aed: float, kind: str = "PROPOSAL_VALUE", actor: str = "system") -> dict:
    """Route a value through the matrix and open a PENDING approval."""
    with psycopg.connect(PG_DSN) as conn:
        route = route_amount(conn, amount_aed)
        if not route:
            raise ValueError(f"no approval rule covers {amount_aed} AED")
        rule_id, role, sla = route
        # idempotency: one open PROPOSAL_VALUE approval per opp
        open_row = conn.execute(
            "SELECT id, routed_to_role, status FROM approvals WHERE opp_id=%s AND kind=%s AND status='PENDING'",
            (opp_id, kind)).fetchone()
        if open_row:
            return {"approval_id": open_row[0], "routed_to": open_row[1], "status": open_row[2],
                    "note": "already pending (idempotent)"}
        aid = conn.execute(
            "INSERT INTO approvals (opp_id, kind, amount_aed, routed_to_role, rule_id) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id", (opp_id, kind, amount_aed, role, rule_id)).fetchone()[0]
        audit(conn, actor, "approval", "approval_routed", opp_id,
              new=f"{amount_aed} AED -> {role} via {rule_id}")
        conn.commit()
        return {"approval_id": aid, "amount_aed": amount_aed, "routed_to": role,
                "rule": rule_id, "sla_hours": sla, "status": "PENDING"}


def decide(approval_id: int, approver: str, decision: str, comment: str = "") -> dict:
    decision = decision.upper()
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError("decision must be APPROVED or REJECTED")
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute("SELECT opp_id, status FROM approvals WHERE id=%s",
                           (approval_id,)).fetchone()
        if not row:
            raise ValueError("unknown approval")
        if row[1] != "PENDING":
            return {"approval_id": approval_id, "status": row[1], "note": "already decided (idempotent)"}
        conn.execute(
            "UPDATE approvals SET status=%s, decided_by=%s, decided_at=now(), comment=%s WHERE id=%s",
            (decision, approver, comment, approval_id))
        audit(conn, approver, "approval", f"approval_{decision.lower()}", row[0],
              new=f"approval {approval_id}: {decision}", reason=comment or None)
        conn.commit()
    return {"approval_id": approval_id, "status": decision, "decided_by": approver}
