"""Audit service (spec §25) — append-only. No update/delete functions exist here by design."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import CFG, Config


def audit(
    conn: sqlite3.Connection,
    *,
    opp_id: str | None,
    actor: str,
    component: str,
    action: str,
    previous_value: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
    source: str | None = None,
    confidence: float | None = None,
    approval_ref: int | None = None,
    cfg: Config = CFG,
) -> None:
    conn.execute(
        """INSERT INTO audit_log
           (opp_id, actor, component, action, previous_value, new_value,
            reason, source, confidence, approval_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (opp_id, actor, component, action, previous_value, new_value,
         reason, source, confidence, approval_ref),
    )
    # Mirror to daily append-only file (§25 immutable trail)
    from datetime import datetime
    line = (f"{datetime.now().isoformat()} | {opp_id or '-'} | {actor} | {component} | "
            f"{action} | prev={previous_value} | new={new_value} | reason={reason}\n")
    log_file = cfg.audit_dir / f"{datetime.now():%Y-%m-%d}.log"
    cfg.audit_dir.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)
