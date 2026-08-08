# NationLabs Orchestrator — BUILD LOG

Baseline: Architecture v2.0 + Phase 0 Discovery (frozen 07-Aug-2026)
Rules: one backlog item at a time · acceptance test must pass before next item · air-gap only · no redesign without flagged blocker.

---

## P1-01 — Resize and validate the AI VM — ✅ PASSED (08-Aug-2026)

**Acceptance criteria (Phase 0 §10, amended 08-Aug — see deviation D-01):** ≥16 vCPU; ≥36 GiB RAM (amended from ≥48); `nvidia-smi` clean; containers healthy; report committed.

### Final verified results (executed by Raghu, guided session)

| Check | Before | After | Verdict |
|---|---|---|---|
| vCPU | 8 | **16** | ✅ |
| RAM | 23 GiB (422 Mi swap used) | **35 GiB, swap 0 B** | ✅ (deviation D-01) |
| GPU | A30, ECC 0 | A30, **ECC 0** | ✅ |
| Containers | 3 known | **6/6 auto-started**: ollama, guardrails-prod, guardrails-uat, **grafana, loki, open-webui** | ✅ |

### How it was executed

Off-site block resolved: Raghu ran guided commands himself (SSH + host RDP). VM real name discovered: `NL-AI-Inference-01`. Graceful `sudo shutdown -h now` from inside → `Set-VMProcessor -Count 16` + `Set-VMMemory -StartupBytes 36GB` on host → `Start-VM` → all 6 containers self-recovered within 4 minutes. Downtime ~5 min.

### Deviation D-01 (flagged, architecture unchanged)

Planned ≥48 GiB (v2.0 band 56–72) → delivered 36 GB static. **Reason:** host NLABDLAS01 had ~114/128 GB allocated across 10 running VMs; even after Raghu powered off 3 SAAD VMs, only 18.6 GB physical free; +12 GB keeps ~6 GB host headroom. **Follow-up:** 56 GB static remains the pre-production target — needs host RAM expansion or VM consolidation (owner: Niren/IT). Phase 1 workload fits comfortably in 36 GB (swap now 0).

### New discoveries logged

- **Grafana + Loki already containerized on the AI VM** (ports 3001/3100) — v2.0 observability stack partially pre-built; P1 observability tasks must inventory before deploying anything new.
- **Open WebUI** on :3000 (healthy).
- **`NL-ProposalBuilder-01` VM (16 GB) exists** on the host — prime candidate for the deferred Windows document-worker decision (D1).
- 3 SAAD VMs powered off by Raghu to free RAM — flagged to confirm with their owner.

**P1-03 — Docker Compose MVP stack — ✅ ACCEPTANCE PASSED (08-Aug-2026)**

### Design note (logged, no redesign)

PostgreSQL stays **native/systemd** (owns PITR cron + audit schema — containerizing would orphan them); Ollama container untouched. Compose stack = `nl-api` (FastAPI) + `nl-worker` (LangGraph), reaching host services via `host.docker.internal`.

### What was built (`build/p1-03/app/`, repo commit c379ec9)

- `main.py` — FastAPI monolith skeleton: `/healthz` (Postgres + Ollama dependency checks), `/audit/probe` (writes via `orchestrator_app` into hash-chained audit_log)
- `worker.py` — LangGraph one-node graph with `PostgresSaver` checkpointing + Postgres wait-loop for cold-boot races
- `docker-compose.yml` — both services `restart: unless-stopped`, API healthcheck, `.env`-fed `PG_APP_PASSWORD`
- `requirements.txt` — pinned (fastapi 0.115.12, langgraph 0.4.8, langgraph-checkpoint-postgres 2.0.21, psycopg 3.2.7) for air-gap reproducibility

### Acceptance results (all 4 passed)

1. `/healthz` → `"status":"ok"`, PostgreSQL 16.14 + Ollama (3 models) ✅
2. `/audit/probe` → audit row seq 4, entry_hash chained ✅
3. Worker log → `CHECKPOINT PERSISTED in PostgreSQL — resume-capable` ✅
4. `checkpoints`/`checkpoint_writes`/`checkpoint_blobs`/`checkpoint_migrations` tables exist (owner orchestrator_app) ✅

### Issues hit & fixed (all logged as config learning)

- **I-04:** `.env` placeholder pasted literally (twice) → password reset to URL-safe build password `NlOrch2026SecurePassX9`. ⚠️ **Security task logged: rotate before production** (password has appeared in chat).
- **I-05:** pg_hba rejected containers: Compose network is `172.19.0.x`, not default bridge `172.17.0.0/16`. Widened to `172.16.0.0/12` scoped to orchestrator_app+orchestrator DB only. `listen_addresses` = localhost + Docker bridge.
- **I-06 (root cause of boot race):** first reboot showed Postgres bound only `127.0.0.1` — it started before Docker created the `172.17.0.1` bridge and silently bound what it could. Fixed with systemd drop-in `/etc/systemd/system/postgresql@16-main.service.d/after-docker.conf` (`After=docker.service`).
- **Reboot-survival test: ✅ PASSED (2nd reboot)** — 43 s after boot: all 8 containers up (nl-api healthy, nl-worker, ollama, guardrails ×2, grafana, loki, open-webui), healthz `"status":"ok"`, zero manual intervention. Criterion ≤3 min — beat by 4×.

**P1-07 — Real LangGraph workflow — ✅ PASSED (08-Aug-2026)**

### Built (`build/p1-07/app/`, commits 9add26d/eedc2c3)

- `prompts.py` — merged extraction+classification single-call prompt (reused from prototype's proven v1 prompts, per v2.0 §10)
- `workflow.py` — LangGraph: intake → analyze (qwen3:14b, format=JSON schema, temp 0) → deterministic readiness gate (weighted fields, threshold 65) → READY | CLARIFICATION_REQUIRED; clarification loop merges human answers and re-scores
- `db.py` — opportunities/clarifications/token_metrics DDL; `main.py` — REST endpoints
- Idempotency guard: analyze_node skips LLM if extraction exists → zero duplicate side-effects on resume

### Acceptance evidence (live, on aiinference)

| Test | Result |
|---|---|
| Complete RFP (ADNOC/Fortinet) | `NL-OPP-2026-0001` → READY, readiness 75, CP + Network security, correct extraction ✅ |
| Vague RFP (laptops) | `NL-OPP-2026-0002` → **CLARIFICATION_REQUIRED**, readiness 0, `needs_human_decision=true`, 9 questions generated — system halted instead of guessing ✅ |
| Clarification loop | Answers merged → READY (90) ✅ |
| Idempotent resume | `llm_calls_total = 2` after graph ran 3× — **no duplicate LLM call** ✅ |
| Token metrics | 845→197 tok cold (48.8s incl. model load); **789→114 tok, 3.3s warm** — steady-state intake latency ✅ |

### Observations logged for P1-23 benchmark

- Model missed explicit "submit proposal by Aug 20" deadline in 0001 (extraction recall gap on deadline phrasing) — flow still correct; becomes a benchmark test case.
- Worker service retired (graph runs in API process); dedicated worker returns in P1-10 (follow-up scheduler).

### Next task

**P1-09 — Deal-registration gate + idempotent RFQ drafting** (highest business value per your deal-reg emphasis; P1-08 vendor service needed first — real vendor Excel still an owner input).

**P1-02 — PostgreSQL 16 + pgvector + PITR + audit schema — ✅ PASSED (08-Aug-2026)**

### What was installed (guided mode, executed by Raghu on aiinference VM)

| Component | Detail | Verification |
|---|---|---|
| PostgreSQL 16 | 16.14 via PGDG official repo (`apt.postgresql.org`); VM had a controlled internet window — no USB bundle needed | `pg_lsclusters`: 16/main online :5432 ✅ |
| pgvector | 0.8.6, extension enabled inside `orchestrator` DB | `\dx`: vector 0.8.6 ✅ |
| App role + DB | `orchestrator_app` (least privilege) owns `orchestrator` DB | `\du` ✅ (password recorded by Raghu — needed in P1-03) |
| WAL archiving | `archive_mode=on`, archive→`/var/lib/postgresql/wal_archive`, `archive_timeout=1h` | Segments 0001–0005 archived ✅ |
| Append-only hash-chained audit | `audit_log` + triggers: UPDATE/DELETE rejected; SHA-256 chain via pgcrypto; script at `build/p1-02/audit_schema.sql` | Forgery attempt → `ERROR: audit_log is append-only` (both ops) ✅ |
| PITR | Base backup + WAL replay to `2026-08-08 08:41:22+00` in scratch cluster | Recovered 2 rows, "disaster" row correctly absent ✅ |
| Automated backups | cron (postgres user): daily 02:17 `pg_basebackup`, 7-day retention | `crontab -l` verified ✅ |

### Issues hit & resolved (learning value logged)

- **I-02:** First PITR drill failed: `recovery ended before configured recovery target was reached` — target WAL segment still open in live DB. Fixed by `pg_switch_wal()`; lesson made permanent via `archive_timeout=1h`. Rule: recovery floor = last *archived* segment.
- **I-03:** Data page checksums OFF (initdb default). Enabling requires cluster re-init — deferred to pre-production hardening list (owner: pre-go-live).

### Open items carried

- VM-side local git repo for configs/SQL (air-gap-safe VCS) — next SSH session.
- Off-box backup copy (same-disk archive ≠ full DR) — production DR decision with Niren (D6/DR).

### Next task

**P1-03 — Docker Compose MVP stack: FastAPI + PostgreSQL + Ollama + LangGraph workers, health checks, reboot persistence.**

---

## History — P1-01 blocked period (07-Aug, resolved 08-Aug)

- Off-site laptop (10.212.134.200) had no route to the air-gapped 192.168.71.x segment; execution shifted to guided mode (Raghu's hands, Kimi's commands) — kept as the working pattern for VM-side tasks.
- Artifacts from the blocked period retained for reuse: `build/p1-01/vm-validate.sh` (generic acceptance checker — RAM threshold updated to 36 GiB), `build/p1-01/vm-resize-hyperv.ps1` (reference runbook; actual resize was done interactively).
