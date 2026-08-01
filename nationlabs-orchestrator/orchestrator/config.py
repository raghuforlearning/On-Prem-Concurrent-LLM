"""Configuration — all policy values live here or in config.yaml, NEVER in prompts (spec §22.3).

Precedence: environment variables > config.yaml > defaults below.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Runtime root: /opt/nationlabs on the VM; ./nationlabs_runtime in dev
RUNTIME_ROOT = Path(os.environ.get("NL_RUNTIME_ROOT", "nationlabs_runtime"))


@dataclass
class Config:
    # --- Ollama ---
    ollama_url: str = "http://192.168.71.11:11434"
    model_main: str = "qwen3:14b"        # extraction, classification, drafting, quotes
    model_fast: str = "gemma3:4b"        # parsing, summaries, guard rails
    llm_timeout_s: int = 300
    llm_max_retries: int = 1             # exactly one retry on JSON parse failure (arch rule 3)

    # --- Paths (derived from RUNTIME_ROOT) ---
    runtime_root: Path = RUNTIME_ROOT
    db_path: Path = RUNTIME_ROOT / "db" / "orchestrator.db"
    inbox: Path = RUNTIME_ROOT / "inbox"
    outbox: Path = RUNTIME_ROOT / "outbox"
    proposals: Path = RUNTIME_ROOT / "proposals"
    data: Path = RUNTIME_ROOT / "data"
    audit_dir: Path = RUNTIME_ROOT / "logs" / "audit"
    rfp_archive: Path = RUNTIME_ROOT / "rfp_archive"

    # --- Business policy (§22 — configurable, not hard-coded into prompts) ---
    finance_threshold_aed: float = 200_000.0
    default_margin_percent: float = 15.0
    min_margin_percent: float = 8.0
    vat_percent: float = 5.0             # UAE VAT
    min_quote_validity_days: int = 25
    pricing_deviation_flag_pct: float = 15.0
    quotes_required_for_proposal: int = 2

    # --- Follow-ups (§15) ---
    followup_time: str = "09:00"         # Asia/Dubai, business mornings only
    followup_max_before_escalation: int = 3
    timezone: str = "Asia/Dubai"
    business_days: tuple[int, ...] = (0, 1, 2, 3, 4, 6)  # Mon-Fri + Sun (UAE week); Sat off
    uae_holidays: tuple[str, ...] = ()   # ISO dates, populated in config.yaml

    # --- People (fallbacks; ownership_matrix table is primary, §18) ---
    presales_manager_email: str = "presales.manager@nationlabs.example"
    finance_team_email: str = "finance@nationlabs.example"


def load_config() -> Config:
    cfg = Config()
    yaml_path = cfg.runtime_root / "config" / "orchestrator.yaml"
    if yaml_path.exists():
        overrides = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        for k, v in overrides.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    if url := os.environ.get("NL_OLLAMA_URL"):
        cfg.ollama_url = url
    return cfg


CFG = load_config()


def ensure_dirs(cfg: Config = CFG) -> None:
    for p in (cfg.db_path.parent, cfg.inbox, cfg.outbox / "vendor_emails",
              cfg.outbox / "internal_alerts", cfg.outbox / "approval_requests",
              cfg.proposals, cfg.data, cfg.audit_dir, cfg.rfp_archive):
        p.mkdir(parents=True, exist_ok=True)
