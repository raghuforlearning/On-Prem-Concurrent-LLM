"""P1-07 — LangGraph workflow: intake -> analyze (merged LLM call) -> readiness
gate -> READY | CLARIFICATION_REQUIRED -> (answers) -> re-score.

Design guarantees (acceptance criteria):
- Postgres checkpointer: every node boundary is durable; thread_id == opp_id.
- analyze_node is IDEMPOTENT: if extraction already stored, the LLM is NOT
  called again (zero duplicate side-effects on crash-resume).
- Readiness is deterministic code — never the model's opinion (v2.0 §10).
- One token_metrics row per LLM call (prompt/completion tokens + latency).
"""
import hashlib
import json
import os
import time
import httpx
import psycopg
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

from db import PG_DSN, audit
from prompts import ANALYSIS_SYSTEM, ANALYSIS_SCHEMA

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
MODEL = os.environ.get("ANALYSIS_MODEL", "qwen3:14b")
READINESS_THRESHOLD = 65

# readiness weights — ported from prototype intake readiness (proven in demo)
CRITICAL_FIELDS = {
    "customer.customer_org": 20,
    "customer.submission_deadline": 15,
    "customer.contact_name": 5,
    "customer.end_user_org": 10,
    "requirement.technology": 15,
    "requirement.brand": 10,
    "requirement.model": 5,
    "requirement.quantity": 10,
    "requirement.title": 10,
}


class WFState(TypedDict, total=False):
    opp_id: str
    status: str


def _get(d, path):
    cur = d or {}
    for part in path.split("."):
        cur = (cur or {}).get(part)
    return cur


def analyze_node(state: WFState) -> dict:
    opp_id = state["opp_id"]
    with psycopg.connect(PG_DSN) as conn:
        opp = conn.execute(
            "SELECT raw_text, extraction_json, status FROM opportunities WHERE opp_id=%s",
            (opp_id,)).fetchone()
        if opp is None:
            raise ValueError(f"unknown opportunity {opp_id}")
        if opp[1] is not None:                      # idempotency guard
            print(f"[analyze] {opp_id}: extraction exists — skipping LLM call", flush=True)
            return {"status": "ANALYZED"}

        payload = {
            "model": MODEL,
            "system": ANALYSIS_SYSTEM,
            "prompt": f"<<<RFP\n{opp[0]}\nRFP>>>\nAnalyze per schema.",
            "format": ANALYSIS_SCHEMA,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 2000},
        }
        t0 = time.time()
        r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=300)
        r.raise_for_status()
        body = r.json()
        latency = int((time.time() - t0) * 1000)

        result = json.loads(body["response"])       # raises on invalid JSON
        conn.execute(
            "UPDATE opportunities SET extraction_json=%s, classification_json=%s, "
            "status='ANALYZED', updated_at=now() WHERE opp_id=%s",
            (json.dumps(result["extraction"]), json.dumps(result["classification"]), opp_id))
        conn.execute(
            "INSERT INTO token_metrics (opp_id, node, model, prompt_tokens, completion_tokens, latency_ms) "
            "VALUES (%s,'analyze',%s,%s,%s,%s)",
            (opp_id, MODEL, body.get("prompt_eval_count"), body.get("eval_count"), latency))
        audit(conn, MODEL, "workflow", "analysis_complete", opp_id,
              new=",".join(result["classification"]["proposal_types"]))
        conn.commit()
    return {"status": "ANALYZED"}


def readiness_node(state: WFState) -> dict:
    opp_id = state["opp_id"]
    with psycopg.connect(PG_DSN) as conn:
        ext = conn.execute(
            "SELECT extraction_json FROM opportunities WHERE opp_id=%s", (opp_id,)).fetchone()[0]
        score, missing = 0, []
        for path, weight in CRITICAL_FIELDS.items():
            if _get(ext, path) not in (None, "", []):
                score += weight
            else:
                missing.append(path)
        status = "READY" if score >= READINESS_THRESHOLD else "CLARIFICATION_REQUIRED"
        conn.execute(
            "UPDATE opportunities SET readiness_score=%s, missing_fields=%s, status=%s, updated_at=now() "
            "WHERE opp_id=%s", (score, missing, status, opp_id))
        if status == "CLARIFICATION_REQUIRED":
            for field in missing:
                conn.execute(
                    "INSERT INTO clarifications (opp_id, field, question) "
                    "SELECT %s, %s, %s WHERE NOT EXISTS ("
                    "  SELECT 1 FROM clarifications WHERE opp_id=%s AND field=%s AND answer IS NULL)",
                    (opp_id, field, f"Please provide: {field}", opp_id, field))
        audit(conn, "system", "workflow", "readiness_computed", opp_id,
              new=f"{score}/{status}", reason="missing: " + ",".join(missing) if missing else None)
        conn.commit()
    return {"status": status}


def build_graph(checkpointer):
    g = StateGraph(WFState)
    g.add_node("analyze", analyze_node)
    g.add_node("readiness", readiness_node)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "readiness")
    g.add_edge("readiness", END)
    return g.compile(checkpointer=checkpointer)


def run_workflow(opp_id: str) -> dict:
    with PostgresSaver.from_conn_string(PG_DSN) as cp:
        cp.setup()
        graph = build_graph(cp)
        return graph.invoke({"opp_id": opp_id, "status": "INTAKE"},
                            config={"configurable": {"thread_id": opp_id}})


def intake(raw_text: str, source_channel: str, conn,
           extraction_method: str = None, original_path: str = None,
           original_filename: str = None) -> str:
    from db import next_opp_id
    opp_id = next_opp_id(conn)
    digest = hashlib.sha256(raw_text.encode()).hexdigest()
    conn.execute(
        "INSERT INTO opportunities (opp_id, status, source_channel, raw_text, raw_sha256, "
        "extraction_method, original_path, original_filename) "
        "VALUES (%s,'INTAKE',%s,%s,%s,%s,%s,%s)",
        (opp_id, source_channel, raw_text, digest, extraction_method, original_path, original_filename))
    audit(conn, "api.user", "workflow", "opportunity_created", opp_id,
          new=source_channel, reason=f"method={extraction_method}" if extraction_method else None)
    conn.commit()
    return opp_id


def submit_answers(opp_id: str, answers: dict) -> dict:
    """Clarification loop: merge answers into extraction, then re-run readiness."""
    with psycopg.connect(PG_DSN) as conn:
        ext = conn.execute(
            "SELECT extraction_json FROM opportunities WHERE opp_id=%s", (opp_id,)).fetchone()[0]
        for field, value in answers.items():
            conn.execute(
                "UPDATE clarifications SET answer=%s, answered_at=now() "
                "WHERE opp_id=%s AND field=%s AND answer IS NULL", (value, opp_id, field))
            parts = field.split(".")
            node = ext.setdefault(parts[0], {})
            node[parts[1]] = value
        conn.execute(
            "UPDATE opportunities SET extraction_json=%s, updated_at=now() WHERE opp_id=%s",
            (json.dumps(ext), opp_id))
        audit(conn, "api.user", "workflow", "clarifications_answered", opp_id,
              new=json.dumps(answers))
        conn.commit()
    with PostgresSaver.from_conn_string(PG_DSN) as cp:
        cp.setup()
        graph = build_graph(cp)
        # resume from readiness — analyze_node's idempotency guard skips the LLM
        return graph.invoke({"opp_id": opp_id, "status": "ANALYZED"},
                            config={"configurable": {"thread_id": opp_id}})
