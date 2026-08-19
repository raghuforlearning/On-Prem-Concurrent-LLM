# CURRENT-STATE.md — NationLabs AI Presales Orchestrator

## Status

**Build mode is active.**

Architecture v2.0 and Phase 0 are the implementation baseline.

Current validated milestone:

**P1-25 PASSED**

TP production-fidelity status:

**P1-20 AUTOMATED GATE IMPLEMENTED; LIVE TP QUARANTINED (19-Aug-2026)**

Document-worker status:

**P1-21 FOUNDATION IMPLEMENTED; CANDIDATE-VM ACCEPTANCE PENDING (19-Aug-2026)**

Production-server UAT preparation:

**P1-OPS-UAT-PREP DONE (14-Aug-2026)**

Historical-dataset collection tooling:

**P1-14 TOOLING PASSED (14-Aug-2026); OWNER DATA COLLECTION PENDING**

Validated implementation branch:

`codex/p1-25-security-hardening`

The exact task commit SHA is reported in the completion handoff after commit creation.

Date of this validated baseline: 19-Aug-2026.

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
- deterministic `Decimal` line/subtotal/VAT/total validation
- configurable currency, totals, VAT and required-terms policy
- persisted validation history and readiness status
- mismatch-to-human-review routing with hash-chained audit evidence
- no automatic correction of vendor figures and no LLM money path

### UI
- human-in-loop review board
- opportunity pipeline
- extraction/classification view
- clarification answering
- RFQ/deal-registration controls
- approvals inbox
- alerts
- token meter

### Approved-content RAG
- PostgreSQL/pgvector knowledge documents, chunks and 1,024-dimensional vectors
- explicit content class, approval, security, validity, expiry and scope metadata
- human-only approval and fail-closed prompt-injection screening
- structure-aware chunks with pricing/table-row integrity
- hybrid HNSW semantic and PostgreSQL full-text retrieval
- complete citation provenance and audited retrieval events
- accepted validated quote facts kept separate from RAG language
- queued local `qwen3:14b` grounded drafting with one worker
- live `bge-m3` adapter validation against the internal Ollama service

### Multi-vendor / multi-quote comparison
- recorded human-supplied AED exchange rates with date/source provenance
- native-currency-preserving side-by-side quote and line-item matrix
- deterministic AED normalization, canonical result JSON and immutable hashes
- preserved comparison runs with exact quote/version/validation/rate inputs
- human quote/version selection and frozen commercial snapshot
- explicit selected/not-selected decision history and audit events
- per-vendor Deal Registration visibility; comparison may proceed while pending,
  while proposal eligibility remains fail-closed

### Proposal Builder handoff and live document generation
- frozen commercial payload, precondition gates and Builder job/audit tracking
- configurable `v1_async` or existing synchronous Builder transport
- live authenticated CP and AMC generation through the frozen Builder's existing
  `/api/generate` endpoint
- live TP generation through the frozen Builder's existing
  `/api/generate-tp-vendor` upload endpoint
- TP source files restricted to controlled local artifact roots and verified by
  SHA-256 before upload
- returned DOCX artifacts archived in an Orchestrator-owned Docker volume with
  SHA-256, payload and validation provenance
- live CP and AMC synthetic transport acceptance passed on 18-Aug-2026

### TP golden-fidelity and customer-commercial safety
- TP requires a distinct approved customer-facing costing snapshot; the
  accepted vendor quote is not used as customer selling price
- deterministic quantity x unit price, subtotal, VAT and grand-total checks
  run before the frozen Builder is called
- internal cost, buy-price, margin and markup fields are rejected from the
  customer-commercial contract
- generated TP validation checks DOCX integrity, exact
  `Proposed BOQ -> Commercials -> Acceptance` order, required tables, frozen
  selling facts, prohibited internal labels, approved RAG provenance and the
  golden 16-inline-shape floor
- failed document validation is persisted and moves the build and proposal to
  `QUARANTINED`; release remains blocked
- the 19-Aug live TP passed section/table/commercial/provenance checks but had
  only 3 inline shapes versus the golden requirement of 16 and therefore was
  correctly quarantined
- Word-rendered inspection found 9 output pages versus the 26-page golden,
  nested synthetic CP content in the test appendix, an incorrect/stale TOC
  page reference and visible layout drift; this output is not production-ready

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

The active P1-25 implementation is under `build/p1-25/app/`. The legacy
`nationlabs-orchestrator/` Flask/SQLite tree is not current.

The frozen Proposal Builder repository had a pre-existing untracked overview
document during takeover. It was not modified or included in Orchestrator work.

## Next implementation area

**P1-E - Benchmarking and security**

P1-25 Orchestrator security hardening is **passed**. It adds local file security
screening/quarantine events, prompt-injection regression checks, RBAC policy
verification helpers, restore-verification evidence, security event persistence,
audit linkage and secrets-hygiene regression checks without cloud/SaaS scanners.

Core Orchestrator implementation exists through P1-25. The former live Proposal
Builder endpoint blocker is resolved through the frozen Builder's existing
synchronous contracts, but production exit gates remain:
- the P1-20 automatic gate is implemented, but its live golden-fidelity
  acceptance failed and correctly quarantined the TP.
- P1-21 is now required for production to resolve Word/PDF rendering and visual
  fidelity without modifying the frozen Proposal Builder.
- P1-21 now has an Orchestrator-owned immutable render contract, serialized
  Word runner, exact-PID watchdog cleanup and quarantine evidence. A live local
  run of the real quarantined Builder TP timed out twice at 90 seconds and was
  cleanly quarantined with no ghost Word process. A Builder CP working copy
  opened, updated, repaginated and saved, but Word PDF export did not return
  within 180 seconds and was also cleanly quarantined. This is feasibility
  evidence, not acceptance; WT-1, WT-2, WT-4 and WT-7 still require a dedicated
  candidate Windows/Office VM and service account.
- P1-24 requires the real P1-14 labelled historical dataset benchmark run.
- Production ops controls such as ClamAV/Wazuh/full isolated restore drills
  remain deployment/operations activities.

The P1-14 owner-data activity now has a committed collection pack, human label
workbook, fail-closed validator and completeness report. P1-14 is not fully
accepted until at least 30 real deals are collected and second-person validated.

The next work should be performed only inside the Orchestrator and should respect the frozen external-system boundaries.

Production UAT preparation has been added without changing frozen external
systems:
- `build/p1-25/app/docker-compose.yml` now allows `.env` overrides for the
  Orchestrator HTTP port, PostgreSQL host/port/database and Ollama endpoint.
- `build/p1-25/app/.env.example` documents the production-safe placeholders.
- `docs/Orchestrator-Production-UAT-Runbook.md` defines the production-server
  UAT deployment sequence, smoke checks, rollback and business-live gates.

This enables a future internal deployment on `192.168.71.2`, but the current
UAT remains local in Docker. The 14-Aug-2026 Hyper-V check found only 4.1 GB
available host RAM, so a dedicated Orchestrator VM is deferred until the system
is production-ready and host capacity is expanded or safely reclaimed. Do not
co-host Orchestrator services inside the frozen AI Inference or Proposal Builder
VMs as a workaround.

## Owner inputs still pending

From Phase 0:
- real vendor-master Excel
- real ownership matrix
- signed approval worksheet AM-1
- 30–50 historical evaluation deals
- final golden AMC confirmation
- Windows/Office document-worker decision and candidate VM for P1-21

These do not block all coding, but dependent acceptance tests cannot be signed off without them.
