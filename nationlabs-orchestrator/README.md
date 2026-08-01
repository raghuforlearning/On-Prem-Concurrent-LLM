# NationLabs AI Presales Orchestrator

End-to-end presales automation for NationLabs — from informal WhatsApp/verbal
requirements to validated, approval-routed proposals. **Fully air-gapped.**
Built to the *NationLabs AI Presales Orchestrator* spec (docx, 34 sections).

## Architecture

```
Web UI (FastAPI :8100) ──► Orchestrator (deterministic state machine, SQLite)
                              │
        ┌─────────────────────┼──────────────────────────┐
        │                     │                          │
   AI Worker (Ollama)    Deterministic services      Audit (append-only)
   qwen3:14b — extract,  vendor matching, readiness, file + SQLite mirror
   classify, draft,      disclosure policy, costing,
   quote extraction      follow-up scheduling,
   gemma3:4b — parse,    approval routing
   summarise, guard
```

**Non-negotiable rules enforced in code (never in prompts):**
- The system has **no SMTP capability**. Every email is a file in
  `/opt/nationlabs/outbox/` dispatched by a human (spec §14).
- End-user details flow **only** to OEM/authorized Distributor tiers, and only
  after explicit owner approval (§11). Resellers get `CONFIDENTIAL` — always.
- LLMs never do math, vendor lookup, or status transitions. qwen3:14b + gemma3:4b
  are the ONLY models invoked.
- LLM structured output: `format=json` + jsonschema validation + **one** retry,
  then escalate to a human. Never silent-guess.
- Ambiguous classification → halt and ask (no silent default).

## Model routing (A30 24GB — both models resident)

| Task | Model |
|---|---|
| Requirement extraction, CP/TP/AMC classification, RFQ/reply drafting, quote extraction | `qwen3:14b` (`/no_think`; thinking ON only as manual second opinion) |
| Vendor-response classification (19 types), summaries, guard checks | `gemma3:4b` |
| Readiness score, vendor matching, contact validation, costing/VAT/margin, 200K routing, follow-ups, state machine | **Python — no model** |

## Layout

- `orchestrator/` — package: config, db (11 tables), ollama_client, statemachine,
  audit, services/{intake, analysis, vendor, comms, followup, responses, costing},
  prompts/ (versioned), web/ (FastAPI + vendored assets)
- `scripts/import_registers.py` — Excel (vendor_master, ownership_matrix) → SQLite
- `data_templates/` — the two Excel templates + generator
- `tests/` — pytest (10 tests, LLM mocked): privacy rule, routing boundary,
  follow-up ladder/stops, JSON retry, blocked contacts
- `deploy/` — Dockerfile, Dockerfile.offline, docker-compose.yml,
  build_transfer_bundle.sh (connected machine), install_offline.sh (VM)
- `nationlabs_runtime/` — dev mirror of `/opt/nationlabs/`

## Run (dev, this PC)

```bash
pip install -r requirements.txt
python orchestrator/db.py                       # init DB
python data_templates/make_templates.py         # create Excel templates
python scripts/import_registers.py              # seed vendors/ownership
uvicorn orchestrator.web.app:app --port 8100    # UI
```

## Deploy (air-gapped VM)

1. Connected machine: `bash deploy/build_transfer_bundle.sh` → USB
2. VM: `bash deploy/install_offline.sh`
3. UI at `http://192.168.71.11:8100`; Ollama must be reachable at :11434
   (already running). Set `OLLAMA_KEEP_ALIVE=-1` for both models.

## Day-2 operations

- **New RFP** → Intake page: paste WhatsApp text or drop file → open opportunity →
  **Run Analysis** → review extraction/classification/readiness.
- **RFQs** → "Match Vendors & Draft RFQs" (tick disclosure approval only when
  §11 conditions are met) → review drafts in outbox → **Approve** → dispatch
  manually → **Confirm Sent** (starts follow-up ladder).
- **Vendor replies** → "Paste vendor response" on the RFQ → auto-classified;
  quotes auto-extracted → **Validate Costing** → with ≥2 Complete quotes,
  **Route for Approval** (>200K → Finance, else verifier).
- **Follow-ups** → run daily via followup-cron container (business days, 09:00 GST,
  max 3 then escalation alert).

## Phase 2 backlog (not in this build)

WhatsApp-style voice-note transcription (faster-whisper), ChromaDB learning layer,
full §22.3 policy engine, §23 final-proposal checklist, RBAC/MFA, Loki shipping,
UAE holiday calendar data, SMTP relay (if approved), customer submission workflow.
