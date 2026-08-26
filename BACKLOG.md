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

Status: **TOOLING PASSED (14-Aug-2026) / OWNER COLLECTION PENDING**

Validation evidence:
- `build/p1-25/app/historical_dataset.py` creates the approved idempotent
  `deal-NNN/{rfp,rfq,quotes,costing,proposal,outcome}` structure, copies the
  blank workbook without overwriting evidence, validates labels/artifacts and
  writes a machine-readable completeness report.
- `build/p1-25/app/dataset_pack/labels-template.xlsx` provides human-editable
  `Deals`, `Requirement Truth`, `Quote Truth` and `Security Cases` sheets with
  controlled lists, review metadata and a visible row-completeness indicator.
- synthetic acceptance pack: 30/30 complete deals passed schema/artifact
  validation and all target-mix checks; removal of one quote artifact plus a
  `DRAFT` label failed closed at 29/30.
- full active snapshot: 71 tests run against disposable PostgreSQL 16/pgvector,
  70 passed and the opt-in live Ollama test was skipped; offline image suite
  ran 71 tests with 15 environment-dependent skips.
- real NationLabs evidence was not added to Git. Generated/populated collection
  folders are excluded from both Git and the Docker build context.

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

Current acceptance state:
- tooling acceptance is passed;
- model benchmark sign-off remains blocked until the owner supplies and a
  second presales reviewer validates at least 30 real historical deals.

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

Status: **PASSED - LIVE EXISTING BUILDER TRANSPORT (18-Aug-2026)**

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
- approved CP and AMC paths complete through the frozen Builder's existing authenticated `/api/generate` endpoint,
- TP completes through the existing `/api/generate-tp-vendor` endpoint with a SHA-256-verified source artifact from a controlled local root,
- frozen commercial payload numbers are handed to Builder unchanged,
- artifact and audit linkage are complete,
- returned DOCX artifacts are content-addressed and archived with validation metadata,
- no Proposal Builder source or runtime configuration is modified.

---

## P1-20 — TP golden-fidelity gate

Status: **SOURCE-AWARE V2 GATE IMPLEMENTED / LIVE RE-ACCEPTANCE PENDING (26-Aug-2026)**

The Orchestrator-side deterministic gate is implemented. It validates frozen
Builder output and never edits the DOCX. The 26-Aug v2 profile replaces the
invalid global 16-inline-shape floor with source-aware and relationship-level
evidence.

Use frozen Proposal Builder output.

Validate:
- expected TP structure,
- required embedded objects,
- content population,
- approved RAG language only,
- accepted quote facts only.

Additional approved business rule:
- `Commercials` must immediately follow `Proposed BOQ`,
- TP customer prices must come from an approved costing-sheet snapshot,
- internal vendor cost, margin, markup and buy-price fields must never appear
  in the customer document.

26-Aug v2 implementation evidence:
- TP handoff now requires an explicit masked client code, real-name aliases and
  `mask_client=true`; the adapter maps them to the frozen Builder's existing
  `clientRealName`, `clientAliases` and `maskClient` multipart fields;
- all Word stories, including headers and text boxes, are scanned for surviving
  real-client aliases; only alias ordinals are reported to avoid leaking names
  into logs;
- commercial values are compared as exact normalized `Decimal` tokens, so
  `120000.00` correctly matches rendered `120,000.00` without weakening the
  money gate;
- image relationships must resolve to non-empty, decodable, non-blank media;
  header/footer branding does not count as preserved vendor content;
- detected graphics in the hash-verified vendor PDF/DOCX are compared with
  main-document drawings in the returned DOCX; no fixed golden object count is
  assumed across unrelated vendor documents;
- focused tests: 20 passed; P1-19 through P1-22 offline regressions: 42 passed,
  one expected live skip; complete suite: 109 passed, two expected opt-in live
  skips against disposable PostgreSQL 16/pgvector with the P1-02 audit schema.

Historical 20-Aug v1 live evidence:
- input: controlled `Sample Vendor TP 1.pdf`, SHA-256
  `ea9342af5effeba80991496e598e3dd79ea2c587ae2a2c73b9b3363fa10b8240`;
- DOCX integrity: pass,
- `Proposed BOQ -> Commercials -> Acceptance`: pass,
- BOQ/commercial tables and frozen selling facts: pass,
- prohibited internal commercial labels: pass,
- approved RAG provenance contract: pass,
- generated DOCX SHA-256:
  `8f86e53e0680a0bece5d32dfbb36150614c8fbdc6b11ce8bc490f51317b05a91`,
- the retired golden embedded-object floor reported **5 `python-docx` inline
  shapes vs 16 required**,
- direct OOXML comparison: **12 generated drawings (6 inline + 6 anchored)
  versus 23 golden drawings (17 inline + 6 anchored)**,
- raster visual review: still required; the bundled renderer could not run on
  this Windows host because LibreOffice is not installed,
- resulting state: `QUARANTINED`.

The 19-Aug run that supplied a generated CP as the TP source is superseded. It
proved that the gate quarantines a bad document, but it is not valid vendor-TP
fidelity evidence.

Acceptance:
- TP output passes the agreed golden-fidelity/visual regression threshold before TP is treated as production-ready.

The acceptance condition is not met. Do not waive or mark P1-20 passed. The
reviewed 25-Aug Builder artifact was created without the masking metadata and
still contains real-customer references. Regenerate it through the revised
Orchestrator contract, pass the v2 structural report, then complete human
page-by-page visual approval. The Orchestrator must not repair or rewrite the
Builder DOCX.

---

## P1-21 — Document rendering worker feasibility / implementation

Status: **FOUNDATION IMPLEMENTED / DEPLOYMENT DEFERRED AND CONDITIONAL**

Do not automatically build the Windows/Office worker simply because Architecture v2.0 described it.

P1-20 determined that the frozen Proposal Builder output does not satisfy the
golden TP requirement. A rendering worker can update fields and export PDF but
cannot add missing proposal content or embedded objects. It is therefore not a
remedy for the current P1-20 failure. Do not patch or copy Builder logic into
the Orchestrator.

Proceed to a candidate VM only if both conditions are met:
- the external Builder first produces a DOCX that passes P1-20 structural and
  human visual acceptance;
- the business confirms automatic PDF output is mandatory and the Builder
  remains DOCX-only.

If those conditions are met:
- use the approved Windows document-worker feasibility tests,
- isolate Office automation,
- watchdog,
- serialized jobs,
- quarantine/recovery,
- reboot survival.

19-Aug implementation evidence:
- immutable hash/security-cleared render-job contract implemented;
- durable PostgreSQL queue implemented with idempotent enqueue, a single active
  Office lease, heartbeat, expired-lease reclaim and max-claim quarantine;
- distinct token-protected worker endpoints now provide claim/start/heartbeat,
  hash-verified source download, controlled DOCX/PDF return and completion;
- Windows polling service implemented with source re-verification, live
  heartbeat during Word execution and upload of verified results to a separate
  Orchestrator artifact store;
- worker accepts only controlled local Builder-produced DOCX inputs and rejects
  path escapes, hash mismatches, uncleared inputs and macro-bearing packages;
- Word COM is launched in an isolated hidden process, jobs are serialized,
  outputs are hash-verified, and failures retry once then quarantine;
- focused P1-19 through P1-22 regressions: 34 passed; dedicated queue integration
  tests: 2 passed; full active suite: 83 passed and 19 opt-in/live skips;
- a real quarantined Builder TP exceeded the 90-second Word deadline on both
  attempts; exact PID cleanup succeeded and left no ghost `WINWORD.EXE`;
- an isolated working-copy change allowed the real Builder CP to open, update
  fields, repaginate and save, but Word PDF export still did not return within
  180 seconds; the job was quarantined with no ghost Word process;
- the local run is not candidate-VM acceptance and did not produce a passing
  PDF. WT-1, WT-2, WT-4 (<=60 seconds) and WT-7 still require the approved
  Windows/Office candidate VM and service account.

Do not mark P1-21 passed until the candidate-VM gates and P1-20 TP gate pass.
Do not deploy a candidate VM merely to attempt to repair Builder content.

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

Status: **PASSED (12-Aug-2026) - harness ready**

Replay the historical evaluation dataset against:
- requirement extraction,
- classification,
- vendor/response classification,
- quote integration/extraction path,
- latency,
- structured output validity.

Acceptance:
- automatic benchmark report generated,
- dataset schema validation and persisted case-level results implemented,
- production model sign-off remains blocked until the real 30-50 labelled historical dataset is supplied.

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

Status: **PASSED (12-Aug-2026) - Orchestrator controls**

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
- agreed local security regression suite passes,
- audit, security event and restore-verification evidence exists,
- no unapproved data egress,
- production ops controls such as ClamAV/Wazuh/full isolated restore drill remain deployment activities.

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

Core Orchestrator implementation exists through P1-25. There is no valid
Orchestrator code change that can repair the current P1-20 Builder-output
fidelity failure. P1-21 is conditional, not the automatic next item.

Production UAT preparation is now documented/configurable:
- compose endpoint overrides for production `.env` values,
- production-safe `.env.example` placeholders,
- `docs/Orchestrator-Production-UAT-Runbook.md`.

The Orchestrator remains in local Docker UAT while the Hyper-V host has only
4.1 GB available RAM. Production-server deployment is deferred until the
application is production-ready and dedicated VM capacity is approved.

Immediate action is live v2 acceptance: regenerate a genuine-vendor-input TP
through the Orchestrator using the explicit client-masking metadata, verify the
source-aware structural report, and complete page-by-page human visual review.
P1-14 owner collection/review continues in parallel. The next independent
Orchestrator backlog item that can be completed is P1-24 once the real P1-14
labelled dataset is supplied. Business-live remains blocked until:
- frozen Builder TP output passes the P1-20 structural and visual gate,
- if automatic PDF is confirmed mandatory, conditional P1-21 candidate-VM
  acceptance produces the final hash-tracked PDF,
- P1-24 is run against the real P1-14 labelled historical dataset,
- production backup/restore and security operations are validated on the target
  servers.
