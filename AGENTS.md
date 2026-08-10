# AGENTS.md — NationLabs AI Presales Orchestrator

## 1. Project identity

This repository contains the **NationLabs AI Presales Orchestrator**.

The Orchestrator is the workflow and control layer for the NationLabs presales lifecycle.

It coordinates:
- presales users and approvers,
- the existing NationLabs Local LLM Platform,
- the existing NationLabs Proposal Builder,
- PostgreSQL workflow data,
- RAG knowledge,
- RFQ, quote, approval and follow-up processes.

## 2. Source of truth

For implementation work, use the following priority order:

1. `AGENTS.md` — operating rules for coding agents.
2. `CURRENT-STATE.md` — current validated implementation state.
3. `BACKLOG.md` — approved implementation sequence and acceptance criteria.
4. `docs/NationLabs-Orchestrator-Architecture-v2.0.md` — architecture baseline.
5. `docs/NationLabs-Orchestrator-Phase0-Discovery-Gap-Assessment.md` — discovery evidence and original Phase 1 backlog.
6. `build/BUILD-LOG.md` — detailed historical implementation evidence.

If older files conflict with the documents above, the documents above win.

## 3. Frozen external systems

The following are existing systems and are **not part of the active Orchestrator codebase**:

### A. NationLabs Local LLM Platform
Existing capabilities include:
- Ollama
- Qwen3 14B
- Gemma3 4B
- NeMo Guardrails
- GPU/runtime configuration
- existing monitoring components

Policy:
- Do not redesign it.
- Do not fork it.
- Do not modify its runtime configuration as part of Orchestrator work.
- Consume it only through a defined Orchestrator adapter/client.

### B. NationLabs Proposal Builder
Existing capabilities include:
- deterministic CP generation,
- deterministic TP generation,
- AMC generation,
- quote parsing,
- deterministic costing,
- BOQ/template handling,
- document generation and validation.

Policy:
- Do not redesign it.
- Do not fork it.
- Do not copy its internal business logic into the Orchestrator.
- Do not modify its source as part of Orchestrator tasks.
- Integrate through a defined Orchestrator adapter/interface only.

## 4. Core architecture rule

The **Orchestrator is the only coordinator** between the Local LLM Platform and the Proposal Builder.

The Local LLM must not directly trigger the Proposal Builder.

Required control pattern:

User / Workflow
    -> Orchestrator
        -> Local LLM Adapter
        -> Human / deterministic gates
        -> Proposal Builder Adapter

AI may recommend, extract, classify and draft.

AI must not bypass:
- human approvals,
- Deal Registration gates,
- deterministic commercial validation,
- audit requirements,
- proposal release controls.

## 5. Active technology baseline

The approved Orchestrator stack is:

- Python
- FastAPI
- LangGraph
- PostgreSQL 16
- pgvector
- SQLAlchemy
- Docker / Docker Compose
- local file storage for controlled artifacts
- local Ollama-based inference through an adapter
- server-rendered / lightweight browser UI for MVP

Do not revert the active implementation to the legacy Flask/SQLite/custom-state-machine prototype.

## 6. Current validated baseline

Current known-good milestone:

**P1-13 PASSED**

Known Git baseline:
`3a0488a` — `P1-13 PASSED: review board UI + file intake with OCR provenance`

Completed implementation areas include:
- P1-01 VM sizing/validation
- P1-02 PostgreSQL 16 + pgvector + PITR + hash-chained append-only audit
- P1-03 Docker Compose MVP foundation
- P1-07 LangGraph intake/extract/classify/readiness/clarification workflow
- P1-08 vendor-master service groundwork
- P1-09 Deal Registration / disclosure / idempotent RFQ workflow
- P1-10 follow-up engine
- P1-11 configurable approval engine
- P1-12 follow-up regression fixes
- P1-13 human review UI + multi-format RFP upload/OCR provenance

Before changing code, verify this against:
- `git status`
- `git log --oneline -10`
- `build/BUILD-LOG.md`
- current tests

## 7. Deal Registration policy

Deal Registration remains a workflow gate, but it must not unnecessarily stop useful work.

Allowed while Deal Registration is pending:
- vendor communication,
- RFI/clarification processing,
- quote receipt,
- quote extraction,
- quote validation,
- quote comparison,
- costing preparation.

Required gate before proposal generation/release when Deal Registration is required:
- Deal Registration must be in an acceptable state.

Target states:
- `NOT_REQUIRED`
- `REQUIRED`
- `SUBMITTED`
- `PENDING`
- `APPROVED`
- `APPROVED_WITH_CONDITIONS`
- `REJECTED`
- `EXPIRED`

Do not model Deal Registration as a global mandatory Yes/No rule for all vendors.

## 8. External communication policy

Until an approved email integration is implemented:

- The Orchestrator must not silently claim that it sent email.
- Users may copy/export an RFQ or follow-up and send it through Outlook, phone, WhatsApp or another approved channel.
- The workflow records the communication through actions such as **Mark as Sent** / **Record Follow-up**.
- Incoming vendor responses may be pasted or uploaded manually.
- A received quote should stop the relevant quote follow-up workflow.

Future Microsoft 365/Exchange integration must be implemented as a separate approved integration.

## 9. AI rules

Use Local LLM for:
- requirement extraction,
- classification,
- missing-information analysis,
- RFQ drafting,
- response classification,
- RAG-supported technical language,
- summarization.

Use deterministic code for:
- arithmetic,
- VAT,
- costing,
- margins,
- totals,
- workflow gates,
- approval routing,
- status transitions,
- duplicate-send prevention,
- quote-version control.

LLM output is a claim until validated.

## 10. Concurrency and performance rule

The NVIDIA A30 24 GB is a constrained shared inference resource.

The Orchestrator must use asynchronous queued AI jobs.

Do not launch five heavy Qwen RFP analyses simultaneously.

Target MVP behavior:
- 1–2 heavy LLM jobs concurrently,
- additional jobs queued,
- cheap CPU/file-processing steps may run in parallel,
- Proposal Builder work must not consume the LLM GPU path.

## 11. Working discipline

For every backlog item:

**BUILD -> TEST -> PASS -> DOCUMENT -> COMMIT -> NEXT**

Before starting:
1. Read `CURRENT-STATE.md`.
2. Read `BACKLOG.md`.
3. Read relevant architecture/Phase 0 sections.
4. Inspect the latest implementation, not legacy prototype folders.
5. Inspect `git status` and recent commits.
6. Run the relevant existing tests.

During implementation:
- Work on one approved backlog item at a time.
- Do not redesign architecture unless there is a genuine implementation blocker.
- Reuse proven existing Orchestrator logic where appropriate.
- Do not modify frozen external systems.
- Maintain air-gap compatibility.
- Do not add SaaS/cloud dependencies.
- Do not hard-code secrets.
- Preserve idempotency and auditability.

After implementation:
1. Run the backlog acceptance tests.
2. Run regression tests affected by the change.
3. Update `build/BUILD-LOG.md`.
4. Update `CURRENT-STATE.md`.
5. Update `BACKLOG.md`.
6. Update `RUNBOOK.md` if deployment/operations changed.
7. Commit with the P1 task ID in the message.
8. Report:
   - files changed,
   - commands run,
   - tests run,
   - pass/fail evidence,
   - commit SHA,
   - next recommended task.

Do not mark a task complete while an acceptance test is failing.

## 12. Legacy folders

This repository contains historical work.

Examples:
- root Local LLM infrastructure material,
- `serving/`,
- the legacy `nationlabs-orchestrator/` Flask/SQLite prototype,
- earlier `build/p1-*` snapshots.

Do not assume the oldest folder is the active implementation.

The latest validated P1 implementation and the current-state documents determine the active baseline.

## 13. Stop conditions

Stop and report before proceeding if:
- the implementation conflicts with the frozen architecture,
- a required secret/credential is unavailable,
- a proposed change requires modifying the Local LLM Platform,
- a proposed change requires modifying the Proposal Builder,
- a migration could destroy existing workflow data,
- an acceptance test reveals a production-impacting regression,
- an external integration would create unapproved data egress.

Do not silently work around these conditions.
