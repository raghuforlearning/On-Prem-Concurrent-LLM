# CURRENT-STATE.md — NationLabs AI Presales Orchestrator

## Status

**Build mode is active.**

Architecture v2.0 and Phase 0 are the implementation baseline.

Current validated milestone:

**P1-15 PASSED**

Validated implementation branch:

`codex/p1-15-proposal-builder-adapter`

The exact task commit SHA is reported in the completion handoff after commit creation.

Date of this validated baseline: 11-Aug-2026.

## Product boundary

There are three separate systems:

1. **AI Presales Orchestrator — ACTIVE DEVELOPMENT**
2. **NationLabs Local LLM Platform — FROZEN EXTERNAL SYSTEM**
3. **NationLabs Proposal Builder — FROZEN EXTERNAL SYSTEM**

All new workflow automation is implemented in the Orchestrator.

The Orchestrator is the only coordinator between the Local LLM and Proposal Builder.

## Current implemented capability

### Foundation
- PostgreSQL 16
- pgvector
- PITR backup proof
- append-only hash-chained audit schema
- Docker Compose application foundation
- FastAPI
- LangGraph / PostgreSQL checkpointing

### RFP intake and AI analysis
- RFP text intake
- file upload
- PDF extraction
- XLSX/CSV/DOCX handling
- image OCR
- source-file archival
- SHA-256 provenance
- Qwen-based extraction/classification
- deterministic readiness scoring
- clarification-required halt
- human review

### Vendor / RFQ workflow
- vendor matching groundwork
- Deal Registration gate
- end-user disclosure control
- RFQ drafting
- idempotent RFQ workflow
- human-controlled external-send recording

### Follow-up
- daily follow-up engine
- stop-on-quote behavior
- escalation after configured number of attempts
- regression test fixes for follow-up isolation

### Approvals
- configuration-driven approval rules
- provisional matrix support
- gap-refusal safety
- actor/timestamp audit

### Quote lifecycle
- frozen Proposal Builder HTTP adapter
- typed quote-result normalization
- content-addressed raw quote archive and SHA-256 provenance
- PostgreSQL quote groups, revisions and current-version control
- ingestion-attempt audit and `FAILED_REVIEW` queue
- identical-source idempotency
- quote receipt/extraction while Deal Registration is pending

### UI
- human-in-loop review board
- opportunity pipeline
- extraction/classification view
- clarification answering
- RFQ/deal-registration controls
- approvals inbox
- alerts
- token meter

## Important current decisions

### Proposal Builder
Do not modify it.

The Orchestrator integrates quote extraction through its adapter/interface.

Proposal Builder remains authoritative for the deterministic capabilities it already owns, including proposal generation and its existing document-domain processing.

### Local LLM
Do not modify it.

The Orchestrator uses a Local LLM adapter/model gateway.

No direct Local LLM -> Proposal Builder control path is allowed.

### Deal Registration
Deal Registration is a gate when required.

However, pending Deal Registration does not stop all useful work.

Quote receipt, validation, comparison, costing preparation and clarification work may continue.

Proposal generation/release must remain blocked until the required Deal Registration condition is satisfied.

### Email
No email application is integrated yet.

Current communication model:
- Orchestrator drafts and tracks.
- Human sends externally.
- User records `Mark as Sent` / follow-up activity.
- Vendor responses are pasted/uploaded.
- Received quote stops the relevant follow-up.

Email/Outlook/Microsoft 365 integration is future work.

### Performance
Current physical estate includes:
- Dell PowerEdge R750
- 48 logical CPU cores
- 128 GB host RAM
- NVIDIA A30 24 GB

The active AI VM was increased during P1 work beyond its original 8 vCPU/24 GB baseline.

Inference must remain queue-controlled.

MVP target:
- 1–2 heavy Qwen jobs concurrently
- additional RFPs queued asynchronously

Five simultaneous RFP uploads are acceptable provided heavy LLM processing is queued rather than launched five-at-once.

## Known documentation debt

The repository still contains older documents that describe:
- the Local LLM platform as the main repository purpose,
- direct Proposal Builder -> Local LLM integration,
- DeepSeek as an active model,
- the legacy Flask/SQLite Orchestrator.

Those descriptions are historical and are not the current Orchestrator architecture.

`AGENTS.md`, this file, `BACKLOG.md`, Architecture v2.0 and Phase 0 override those legacy descriptions.

## Known repository condition at handoff

The active P1-15 implementation is under `build/p1-15/app/`. The legacy
`nationlabs-orchestrator/` Flask/SQLite tree is not current.

The frozen Proposal Builder repository had a pre-existing untracked overview
document during takeover. It was not modified or included in Orchestrator work.

## Next implementation area

**P1-C — Quote Intelligence + RAG**

P1-15 is **passed**. Its adapter, provenance/version persistence, failure-review
path, full 18-test regression suite and approved live Proposal Builder contract
all passed without changing the frozen Builder.

The exact next engineering item is **P1-16 — Deterministic quote validation**.
P1-14 historical dataset collection remains an owner/data activity that can
continue separately.

The next work should be performed only inside the Orchestrator and should respect the frozen external-system boundaries.

## Owner inputs still pending

From Phase 0:
- real vendor-master Excel
- real ownership matrix
- signed approval worksheet AM-1
- 30–50 historical evaluation deals
- final golden AMC confirmation
- Windows/Office decision only if later document-rendering work still requires it

These do not block all coding, but dependent acceptance tests cannot be signed off without them.
