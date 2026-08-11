"""P1-08 — Vendor master service (PostgreSQL-backed).

Demo seed for build/testing only — replaced by the real vendor-master Excel
import (Phase 0 §5, action A-5.1, owner: Raghu). Import path accepts the same
15-column schema as the prototype's vendor_master.xlsx.
"""
import psycopg
from db import PG_DSN, audit

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id   SERIAL PRIMARY KEY,
    vendor_name TEXT NOT NULL UNIQUE,
    tier        TEXT NOT NULL,             -- OEM | Distributor | Reseller
    tech_domains TEXT[] NOT NULL,
    oem         TEXT,                      -- NULL for OEMs themselves
    product_family TEXT,
    contact_name TEXT,
    email       TEXT,
    email_domain TEXT,
    country     TEXT,
    vendor_authorised BOOLEAN NOT NULL DEFAULT FALSE,
    deal_reg_capable  BOOLEAN NOT NULL DEFAULT FALSE,  -- blank/absent = FALSE (fail-closed)
    assigned_nl_owner TEXT,
    contact_status TEXT NOT NULL DEFAULT 'ACTIVE'
);
CREATE TABLE IF NOT EXISTS deal_registrations (
    id          BIGSERIAL PRIMARY KEY,
    opp_id      TEXT NOT NULL REFERENCES opportunities(opp_id),
    vendor_id   INT NOT NULL REFERENCES vendors(vendor_id),
    status      TEXT NOT NULL DEFAULT 'REQUESTED',  -- REQUESTED/APPROVED/REJECTED/EXPIRED
    reg_reference TEXT,
    validity    DATE,
    notes       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (opp_id, vendor_id)
);
CREATE TABLE IF NOT EXISTS rfqs (
    rfq_ref     TEXT PRIMARY KEY,          -- NL-RFQ-YYYY-####
    opp_id      TEXT NOT NULL REFERENCES opportunities(opp_id),
    vendor_id   INT NOT NULL REFERENCES vendors(vendor_id),
    status      TEXT NOT NULL,             -- DRAFT/BLOCKED_PENDING_DEAL_REG/READY_TO_SEND/SENT
    draft_body  TEXT,
    disclose_end_user BOOLEAN NOT NULL DEFAULT FALSE,
    disclosure_approved_by TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ
);
"""

# Demo seed: OEMs this client's RFP touches + two distributors (deal-reg paths differ)
SEED = [
    # name, tier, domains, oem, family, contact, email, auth, dealreg, owner
    ("Fortinet", "OEM", ["Network security", "Cybersecurity"], None, "FortiAI/FortiSOAR",
     "Demo Fortinet AM", "am@fortinet.example", True, True, "demo-owner-1"),
    ("CrowdStrike", "OEM", ["Endpoint security", "Cybersecurity"], None, "Falcon Intel",
     "Demo CrowdStrike AM", "am@crowdstrike.example", True, True, "demo-owner-1"),
    ("Tenable", "OEM", ["Cybersecurity", "Monitoring"], None, "Tenable.sc",
     "Demo Tenable AM", "am@tenable.example", True, True, "demo-owner-2"),
    ("SentinelOne", "OEM", ["Endpoint security"], None, "Singularity",
     "Demo S1 AM", "am@sentinelone.example", True, True, "demo-owner-2"),
    ("CoSoSys", "OEM", ["DLP", "Endpoint security", "Data security"], None, "Endpoint Protector",
     "Demo CoSoSys AM", "am@cososys.example", True, True, "demo-owner-2"),
    ("Center for Internet Security", "OEM", ["Cybersecurity"], None, "CIS WorkBench",
     "Demo CIS", "sales@cisecurity.example", True, False, "demo-owner-2"),
    ("Ingram Micro (DEMO)", "Distributor",
     ["Network security", "Endpoint security", "Cybersecurity", "DLP", "Software subscription"],
     None, "Multi-OEM", "Demo Ingram", "presales@ingram.example", True, True, "demo-owner-1"),
    ("Redington (DEMO)", "Distributor",
     ["Network security", "Endpoint security", "Cybersecurity", "Software subscription"],
     None, "Multi-OEM", "Demo Redington", "presales@redington.example", True, True, "demo-owner-1"),
]

# RFP keyword -> vendor matching (demo rulebook; real matching uses tech_domains + product_family)
KEYWORD_MAP = {
    "forti": "Fortinet",
    "crowdstrike": "CrowdStrike",
    "tenable": "Tenable",
    "ten-sc": "Tenable",
    "sentinelone": "SentinelOne",
    "cososys": "CoSoSys",
    "cis workbench": "Center for Internet Security",
}


def init_vendors(conn):
    conn.execute(SCHEMA)
    for name, tier, domains, oem, fam, contact, email, auth, dr, owner in SEED:
        conn.execute(
            "INSERT INTO vendors (vendor_name, tier, tech_domains, oem, product_family, contact_name, "
            "email, email_domain, vendor_authorised, deal_reg_capable, assigned_nl_owner) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vendor_name) DO NOTHING",
            (name, tier, domains, oem, fam, contact, email, email.split("@")[1], auth, dr, owner))
    conn.commit()


def match_vendors(opp_id: str) -> list[dict]:
    """Match RFP content to vendors: direct OEM hit per keyword, plus deal-reg-capable
    distributors as alternates. Returns vendor list with match basis."""
    with psycopg.connect(PG_DSN) as conn:
        raw = conn.execute("SELECT raw_text FROM opportunities WHERE opp_id=%s", (opp_id,)).fetchone()[0].lower()
        oem_names = {v for kw, v in KEYWORD_MAP.items() if kw in raw}
        matched = []
        for name in sorted(oem_names):
            v = conn.execute(
                "SELECT vendor_id, vendor_name, tier, deal_reg_capable, assigned_nl_owner FROM vendors "
                "WHERE vendor_name=%s", (name,)).fetchone()
            if v:
                matched.append({"vendor_id": v[0], "vendor_name": v[1], "tier": v[2],
                                "deal_reg_capable": v[3], "nl_owner": v[4], "basis": "OEM keyword match"})
        distis = conn.execute(
            "SELECT vendor_id, vendor_name, tier, deal_reg_capable, assigned_nl_owner FROM vendors "
            "WHERE tier='Distributor'").fetchall()
        for d in distis:
            matched.append({"vendor_id": d[0], "vendor_name": d[1], "tier": d[2],
                            "deal_reg_capable": d[3], "nl_owner": d[4],
                            "basis": "distributor alternate (deal-reg capable)"})
        audit(conn, "system", "vendor", "vendors_matched", opp_id,
              new=f"{len(oem_names)} OEMs + {len(distis)} distributors")
        conn.commit()
        return matched
