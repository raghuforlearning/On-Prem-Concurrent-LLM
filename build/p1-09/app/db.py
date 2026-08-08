"""P1-07 — Database layer: schema bootstrap + helpers (PostgreSQL, psycopg3)."""
import os
import psycopg

PG_DSN = os.environ["PG_DSN"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    opp_id          TEXT PRIMARY KEY,          -- NL-OPP-YYYY-####
    status          TEXT NOT NULL,             -- INTAKE/ANALYZING/READY/CLARIFICATION_REQUIRED
    source_channel  TEXT,
    raw_text        TEXT NOT NULL,
    raw_sha256      TEXT NOT NULL,
    extraction_json JSONB,
    classification_json JSONB,
    readiness_score INT,
    missing_fields  TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS clarifications (
    id          BIGSERIAL PRIMARY KEY,
    opp_id      TEXT NOT NULL REFERENCES opportunities(opp_id),
    field       TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT,
    asked_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS token_metrics (
    id          BIGSERIAL PRIMARY KEY,
    opp_id      TEXT,
    node        TEXT NOT NULL,
    model       TEXT NOT NULL,
    prompt_tokens INT,
    completion_tokens INT,
    latency_ms  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_schema():
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(SCHEMA)
        conn.commit()


def audit(conn, actor, component, action, opp_id=None, previous=None, new=None, reason=None):
    conn.execute(
        "INSERT INTO audit_log (actor, component, action, opp_id, previous_value, new_value, reason) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (actor, component, action, opp_id, previous, new, reason),
    )


def next_opp_id(conn) -> str:
    from datetime import datetime
    year = datetime.now().year
    row = conn.execute(
        "SELECT opp_id FROM opportunities WHERE opp_id LIKE %s ORDER BY opp_id DESC LIMIT 1",
        (f"NL-OPP-{year}-%",),
    ).fetchone()
    seq = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return f"NL-OPP-{year}-{seq:04d}"
