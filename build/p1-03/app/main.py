"""P1-03 — NationLabs Orchestrator API (FastAPI modular monolith, MVP skeleton).

Scope for P1-03 ONLY: prove the stack wiring. Real workflow modules land in
P1-07+ (per frozen backlog — do not jump ahead).
"""
import os
import time
import httpx
import psycopg
from fastapi import FastAPI
from pydantic import BaseModel

PG_DSN = os.environ["PG_DSN"]                    # e.g. postgresql://orchestrator_app:***@host.docker.internal:5432/orchestrator
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
BOOT_TS = time.time()

app = FastAPI(title="NationLabs Orchestrator", version="0.1.0-p1.03")


@app.get("/healthz")
def healthz():
    """Liveness + dependency readiness. Green only if Postgres AND Ollama answer."""
    checks = {}

    try:
        with psycopg.connect(PG_DSN, connect_timeout=3) as conn:
            checks["postgres"] = conn.execute("SELECT version()").fetchone()[0].split(",")[0]
    except Exception as e:
        checks["postgres"] = f"FAIL: {e}"

    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        checks["ollama"] = f"ok, {len(r.json().get('models', []))} models"
    except Exception as e:
        checks["ollama"] = f"FAIL: {e}"

    ok = all(not str(v).startswith("FAIL") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "uptime_s": round(time.time() - BOOT_TS, 1), **checks}


class AuditProbe(BaseModel):
    actor: str = "p1-03-acceptance"
    note: str = "API container wrote through app role"


@app.post("/audit/probe")
def audit_probe(p: AuditProbe):
    """Acceptance helper: insert via orchestrator_app into the hash-chained audit_log."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "INSERT INTO audit_log (actor, component, action, new_value) "
            "VALUES (%s, 'api', 'p103_probe', %s) RETURNING seq, left(entry_hash,12)",
            (p.actor, p.note),
        ).fetchone()
        conn.commit()
    return {"seq": row[0], "entry_hash": row[1]}
