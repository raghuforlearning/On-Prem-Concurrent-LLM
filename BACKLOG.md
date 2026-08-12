# BACKLOG.md — NationLabs AI Presales Orchestrator

## Working rule

One backlog item at a time:

**BUILD -> TEST -> PASS -> DOCUMENT -> COMMIT -> NEXT**

P1-01 through P1-18 (excluding the owner-data P1-14 activity) are treated as
the validated implementation baseline unless a takeover audit proves otherwise.

---

## Completed baseline

- [x] P1-01 — VM resize / validation
- [x] P1-02 — PostgreSQL 16 + pgvector + PITR + append-only hash-chained audit
- [x] P1-03 — Docker Compose MVP foundation
- [x] P1-07 — LangGraph intake -> extraction/classification -> readiness -> clarification loop
- [x] P1-08 — vendor-master service groundwork
- [x] P1-09 — Deal Registration / disclosure / idempotent RFQ workflow
- [x] P1-10 — follow-up scheduler
- [x] P1-11 — configuration-driven approval engine
- [x] P1-12 — follow-up regression fixes
- [x] P1-13 — human review UI + file intake/OCR provenance
- [x] P1-15 — frozen Proposal Builder adapter + quote lifecycle/provenance/versioning
- [x] P1-16 — deterministic quote validation + review/audit workflow
- [x] P1-17 — approved-content pgvector RAG + queued grounded drafting
- [x] P1-18 — multi-vendor comparison + frozen human quote/version selection

The P1-18 task commit SHA is reported in the completion handoff.

---

# P1-C — Quote Intelligence + RAG

## P1-14 — Historical evaluation dataset pack

Status: **NEXT / OWNER INPUT + TOOLING**

Build:
- folder/validation tooling for historical opportunity dataset,
- label template,
- schema validator,
- dataset completeness report.

Target dataset:
- 30–50 historical deals,
- CP / TP / AMC coverage where available,
- multiple technology domains,
- multiple vendors,
- multi-vendor cases,
- renewals,
- messy/incomplete cases,
- revised quotes,
- at least one arithmetic-error quote.

Acceptance:
- at least 30 complete labelled deals pass schema validation before model benchmark sign-off.

Important:
- do not block independent P1-C engineering while the full dataset is being collected.

---

## P1-15 — Quote lifecycle / Proposal Builder adapter

Status: **PASSED (11-Aug-2026)**

Validation evidence:
- Orchestrator-side HTTP adapter, typed normalization, raw-source archival,
  PostgreSQL lifecycle/version persistence and `FAILED_REVIEW` queue implemented
  under `build/p1-15/app/`.
- full disposable-PostgreSQL suite: 18 passed, including P1-10/P1-12 regressions.
- approved live Proposal Builder contract: passed with its read-only synthetic
  quote fixture, producing 5 normalized AED line items.
- raw archive bytes and SHA-256 provenance, database persistence, quote version,
  audit linkage, pending-Deal-Registration behavior and identical-source
  idempotency all passed.
- no Proposal Builder source was changed and no default/example credential was used.

Architecture decision:
- do not modify Proposal Builder.
- do not copy Proposal Builder internals into the Orchestrator.
- create an Orchestrator-side adapter/interface.

Build:
- `integrations/proposal_builder/` boundary,
- typed request/response schemas,
- health/status handling,
- quote-ingestion handoff,
- structured result persistence in PostgreSQL,
- raw vendor-response provenance,
- failure -> human-review queue,
- quote-version lifecycle.

The exact transport may be:
- existing Proposal Builder API, if already available,
- controlled process/service invocation through a stable adapter,
- another internal interface that does not require modifying Proposal Builder.

Do not assume an API exists until inspected.

Acceptance:
- historical/sample quote can enter the Orchestrator,
- the Orchestrator invokes the frozen Proposal Builder capability through the adapter,
- structured quote result is stored,
- raw source hash/provenance is retained,
- failed/unparsable result becomes `FAILED_REVIEW`,
- no silent data drop,
- no Proposal Builder source change.

---

## P1-16 — Deterministic quote validation

Status: **PASSED (11-Aug-2026)**

Validation evidence:
- pure `Decimal` engine validates line totals, subtotal, VAT, grand total,
  currency confirmation and policy-required validity/payment/delivery terms.
- persisted validation history, `VALIDATED`/`BLOCKED`/`NEEDS_REVIEW` status,
  review-queue linkage and hash-chained audit events implemented.
- seeded arithmetic-error quote remained blocked for 20/20 pure runs and both
  live PostgreSQL validations; vendor claims were not auto-corrected.
- valid quote proceeded with computed AED 28,500.00 subtotal, AED 1,425.00 VAT
  and AED 29,925.00 total.
- full P1-16 image suite: 27 passed; Compose and image-secret checks passed.
- validation engine imports only Python standard-library modules and has no LLM path.

Build Orchestrator-side control checks around structured quote results:
- quote totals,
- VAT,
- line totals,
- currency presence,
- validity/terms presence where required,
- confidence/status handling,
- mismatch workflow,
- human review.

Important:
- do not duplicate Proposal Builder's internal deterministic engine.
- Orchestrator validates the integration contract and workflow readiness.
- commercial arithmetic remains deterministic.

Acceptance:
- seeded arithmetic-error quote is blocked every run,
- valid quote proceeds,
- mismatch creates a review/audit event,
- LLM never becomes source of truth for money.

---

## P1-17 — Approved-content RAG

Status: **PASSED (12-Aug-2026)**

Validation evidence:
- pgvector-backed approved-content store with HNSW semantic search and
  PostgreSQL full-text hybrid ranking.
- SQL prefilters approval, security, content class, validity, expiry and
  customer/vendor scope before scoring.
- ingestion is always `DRAFT`; human approval is role-gated; detected hostile
  prompt-injection content is `FLAGGED` and cannot be approved.
- structure-aware 600-word chunks use 90-word overlap; pricing/table rows stay
  atomic; repeated text under distinct sections retains both provenance records.
- citations carry document/version/status/section/page/source/hash/date/owner/
  score; retrieval and draft transitions are audited.
- accepted commercial values come only from a current deterministically
  `VALIDATED` quote and are passed separately from untrusted RAG context.
- heavy grounded drafting is queued and consumed by one local worker.
- full PostgreSQL 16/pgvector suite: 40 passed, including live `bge-m3`
  (1,024 dimensions) and `qwen3:14b` grounded-output contract tests.
- Compose and image-secret exclusion checks passed; frozen systems were not
  modified by the Orchestrator implementation.

Build:
- pgvector-backed local RAG,
- approved-content filtering,
- document/content metadata,
- chunking rules,
- provenance/citations,
- hybrid retrieval if justified by the approved architecture,
- Local LLM adapter use.

RAG supplies language/knowledge.

RAG must not supply authoritative commercial numbers when an accepted quote exists.

Acceptance:
- retrieval returns only content allowed by approval/status filters,
- source provenance is available,
- proposal/technical drafting receives accepted commercial facts separately,
- hostile/unapproved content cannot silently become authoritative knowledge.

---

## P1-18 — Multi-vendor / multi-quote comparison

Status: **PASSED (12-Aug-2026)**

Validation evidence:
- native currency totals and line amounts remain intact; non-AED amounts are
  normalized only with an explicitly recorded AED rate, date and source.
- comparison result serialization and hash are byte-stable regardless of quote
  input ordering; no LLM or rate network lookup is used.
- comparison runs retain exact quote/version/validation/rate inputs and the
  immutable result JSON/hash.
- human quote selection freezes the selected quote/version and commercial
  snapshot, records every non-selected candidate and creates an audit event.
- old/superseded revisions stay intact and cannot be selected; a pending
  deal-registration quote may be compared/selected but is marked ineligible
  for proposal generation/release until the gate is satisfied.
- full disposable PostgreSQL 16/pgvector suite: 46 passed, including the live
  P1-17 `bge-m3` and `qwen3:14b` smoke test.

Build:
- quote groups and revisions,
- native currency preservation,
- deterministic AED-normalized comparison using recorded rate/date when applicable,
- side-by-side comparison,
- human selection,
- preserved comparison runs,
- selected quote/version freeze.

Deal Registration is evaluated per vendor/quote path when required.

Acceptance:
- three-vendor sample produces a normalized comparison,
- revised quote does not overwrite history,
- rerun with identical deterministic inputs produces identical comparison data,
- human selection is recorded with actor/time,
- rejected/superseded quotes remain auditable.

---

# P1-D — Proposal integration and release

## P1-19 — Proposal Builder handoff

Status: **PASSED - Orchestrator foundation**

Architecture:
- Proposal Builder remains frozen.
- Orchestrator sends an approved, frozen structured payload through the adapter.

Preconditions:
- accepted quote/version,
- required costing validation,
- required approvals,
- Deal Registration gate satisfied or `NOT_REQUIRED`,
- proposal type known.

Build:
- proposal handoff object,
- job/reference tracking,
- returned-artifact metadata,
- SHA-256 artifact tracking,
- failure/retry/human-review state.

Acceptance:
- approved CP path completes through a fake documented Builder adapter without modifying Proposal Builder source,
- frozen commercial payload numbers are handed to Builder unchanged,
- artifact and audit linkage are complete,
- live CP completion remains blocked until the external frozen Proposal Builder exposes `/api/v1/builds`.

---

## P1-20 — TP golden-fidelity gate

Status: **PENDING**

Use frozen Proposal Builder output.

Validate:
- expected TP structure,
- required embedded objects,
- content population,
- approved RAG language only,
- accepted quote facts only.

Acceptance:
- TP output passes the agreed golden-fidelity/visual regression threshold before TP is treated as production-ready.

---

## P1-21 — Document rendering worker feasibility / implementation

Status: **DEFERRED UNTIL REQUIRED**

Do not automatically build the Windows/Office worker simply because Architecture v2.0 described it.

First determine whether the frozen Proposal Builder output already satisfies Alpha requirements without this component.

If still required:
- use the approved Windows document-worker feasibility tests,
- isolate Office automation,
- watchdog,
- serialized jobs,
- quarantine/recovery,
- reboot survival.

---

## P1-22 — Proposal release flow

Status: **PASSED (12-Aug-2026)**

Build:
- final review,
- approval evidence,
- release package,
- DOCX/PDF/hash metadata,
- submission tracking,
- human-controlled external submission.

Acceptance:
- complete opportunity -> proposal lineage recorded,
- no release without required gates,
- final artifacts and hashes recorded,
- customer submission action auditable,
- no external email/send action performed by the Orchestrator.

---

# P1-E — Benchmarking and security

## P1-23 — Benchmark harness

Status: **PENDING**

Replay the historical evaluation dataset against:
- requirement extraction,
- classification,
- vendor/response classification,
- quote integration/extraction path,
- latency,
- structured output validity.

Acceptance:
- automatic benchmark report generated.

---

## P1-24 — Model go/no-go

Status: **PENDING**

Current candidates:
- Qwen3 14B
- Gemma3 4B

Do not treat old DeepSeek documentation as the current model decision.

Benchmark gates decide production routing.

Do not lower thresholds simply to make a model pass.

---

## P1-25 — Security hardening

Status: **PENDING**

Includes:
- controlled file intake,
- malware scanning,
- prompt-injection regression suite,
- authentication/RBAC integration,
- audit verification,
- secrets hygiene,
- dependency/offline package control,
- restore testing,
- data retention/backup review.

Acceptance:
- agreed security regression suite passes,
- audit and restore evidence exists,
- no unapproved data egress.

---

# Future integrations — not Alpha blockers

- Microsoft 365 / Exchange email integration
- calendar/reminder integration
- SSO/AD enhancements
- WhatsApp integration, if ever formally approved
- broader department agents

Until email integration exists:
- human sends communications externally,
- Orchestrator records send/follow-up events,
- incoming vendor responses are pasted/uploaded.

---

# Immediate next engineering task

P1-20 and P1-21 remain blocked/deferred until frozen Proposal Builder build output is available. The next actionable open engineering item is **P1-23 — Benchmark harness**, unless the Builder endpoint is supplied first. P1-14 remains a parallel owner/data activity.
