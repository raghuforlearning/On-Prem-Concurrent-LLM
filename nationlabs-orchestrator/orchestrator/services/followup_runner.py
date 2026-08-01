"""Cron/loop entry point: process due follow-ups once, then exit."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.config import CFG, ensure_dirs
from orchestrator.db import get_db, init_db
from orchestrator.services.followup import run_due_followups

if __name__ == "__main__":
    ensure_dirs()
    init_db(CFG.db_path)
    conn = get_db(CFG.db_path)
    done = run_due_followups(conn)
    conn.commit()
    print(f"processed {len(done)} follow-ups")
