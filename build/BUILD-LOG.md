# NationLabs Orchestrator — BUILD LOG

Baseline: Architecture v2.0 + Phase 0 Discovery (frozen 07-Aug-2026)
Rules: one backlog item at a time · acceptance test must pass before next item · air-gap only · no redesign without flagged blocker.

---

## P1-13 - Clarification Set-button regression fix - PASSED (08-Sep-2026)

- Corrected the review-board clarification handler to use literal DOM element
  IDs for dotted field paths such as `customer.contact_name`.
- Added an explicit missing-input alert and API error feedback so clarification
  failures are no longer silent.
- Verified the fix against local Docker UAT: `customer.contact_name=Mohammad`
  persisted for `NL-OPP-2026-0001`, readiness changed from 30 to 35 and open
  clarifications changed from seven to six.
- Active Orchestrator suite: **93 passed, 19 expected opt-in/live skips**.
- No Local LLM Platform or Proposal Builder source/configuration was changed.

---

## P1-20 - Live fixture correction / genuine vendor-TP acceptance - BLOCKED EXTERNALLY (20-Aug-2026)

### Corrected (`build/p1-25/app/`)

- Removed the invalid live-test fallback that generated a CP and then supplied
  that CP to `/api/generate-tp-vendor` as though it were a vendor TP.
- The opt-in test now requires a pre-existing vendor PDF/DOCX from a controlled
  input archive and an operator-pinned SHA-256.
- The fixture rejects relative paths, out-of-root files, extension/magic
  mismatches, hash mismatches and every file under the generated proposal
  artifact root.
- TP live acceptance now requires `DONE` with a passing P1-20 validation; an
  expected quarantine is no longer counted as acceptance.
- No Proposal Builder or Local LLM file or runtime configuration was changed.

### Evidence

| Check | Result |
|---|---|
| New live-fixture contract tests | **4 passed** |
| Focused P1-19/P1-20 suite | **19 passed** |
| Full active Orchestrator suite | **103 passed, 19 expected opt-in/live skips** |
| Builder health from Orchestrator | **HTTP 200, environment `UAT`** |
| Controlled vendor TP input | **1,407,625 bytes**, SHA-256 `ea9342af5effeba80991496e598e3dd79ea2c587ae2a2c73b9b3363fa10b8240` |
| CP and AMC live subtests | **DONE** |
| TP order/tables/selling facts/leakage/RAG checks | **Passed** |
| TP output | **2,090,445 bytes**, SHA-256 `8f86e53e0680a0bece5d32dfbb36150614c8fbdc6b11ce8bc490f51317b05a91` |
| Golden object floor | **Failed: 5/16 `python-docx` inline shapes** |
| Direct OOXML object comparison | **12 generated drawings vs 23 golden drawings** |
| Corrected live test | **Failed at TP as designed; state `QUARANTINED`** |
| Raster review | **Not completed; LibreOffice is not installed on the UAT Windows host** |

### Decision / next gate

P1-20 remains not accepted. The corrected run proves the frozen Builder
transport works with genuine vendor input, while the produced TP still omits
golden embedded objects. A rendering worker cannot recreate missing proposal
content, so P1-21 is not a content-fidelity remedy. Candidate-VM P1-21 work is
deferred unless a compliant Builder DOCX first exists and automatic PDF output
is confirmed mandatory. Under the frozen-system rule, the Orchestrator must
stop here rather than modify or copy Proposal Builder implementation.

The 19-Aug CP-as-TP run below is retained as historical fail-closed evidence but
is superseded as TP fidelity evidence.

---

## P1-21 - Windows document-worker - FOUNDATION IMPLEMENTED / ACCEPTANCE PENDING (19-Aug-2026)

### Built (`build/p1-25/app/`)

- Added `document_worker.py`: immutable source/clearance hash contract,
  allow-listed local roots, macro rejection, deterministic request identity,
  serialized Office execution, timeout/retry, output hash checks and quarantine.
- Added `windows-document-worker/Invoke-DocumentRender.ps1`: isolated hidden
  Word COM execution, disabled macros/link updates, exact Word PID evidence,
  milestone logs, immutable-source working copy, DOCX save, PDF export and COM
  cleanup.
- Added five focused tests covering contract/security failure, idempotency,
  DOCX/PDF hash verification, two-job serialization and retry/quarantine.
- Added `document_render_queue.py`: durable PostgreSQL queue with idempotent
  enqueue, one active Office lease, heartbeat, recovery and audited quarantine.
- Added a distinct-token internal worker API for controlled Builder-DOCX
  download and rendered DOCX/PDF return. Returned files are size/hash verified,
  stored in a separate Orchestrator volume and registered before completion.
- Added `windows-document-worker/worker_service.py`: polling, source hash
  re-verification, heartbeat during Word execution and verified artifact upload.
- Added queue/API/service tests and a minimal pinned Windows dependency file.
- No Proposal Builder or Local LLM source/runtime configuration was changed;
  no proposal-template or business logic was copied into the worker.

### Evidence

| Check | Result |
|---|---|
| Focused P1-19 through P1-22 regression suite | **34 passed** |
| P1-21 disposable-PostgreSQL queue integration | **2 passed** |
| Full active Orchestrator suite | **83 passed, 19 expected opt-in/live skips** |
| Local Word COM | **16.0, invisible launch confirmed** |
| Real frozen Builder TP | **Timed out twice at 90 s; quarantined** |
| Real frozen Builder CP | **DOCX saved; Word PDF export timed out at 180 s; quarantined** |
| Exact PID cleanup | **Passed; no ghost `WINWORD.EXE`** |
| WT-6 serialization | **Unit passed; maximum Office concurrency 1** |
| WT-8 boundary | **Contract passed** |
| WT-1 / WT-2 / WT-7 | **Not run; candidate VM/service account required** |
| WT-4 candidate threshold | **Not accepted; local deadline was 90 s, required <=60 s** |

### Decision / next gate

P1-21 is not passed. The durable queue and worker loop remove the code-side
transport/resume gap, but cannot repair missing TP content or embedded objects.
After the corrected 20-Aug genuine-vendor-TP run, candidate-VM work is
conditional: a compliant Builder DOCX must first pass P1-20 and the business
must confirm automatic PDF output is mandatory. Only then should IT approve a
dedicated Windows/Office candidate VM and execute WT-1 through WT-8.
See `docs/P1-21-Windows-Document-Worker-Feasibility.md`.

---

## P1-20 - TP golden-fidelity gate - HISTORICAL CP-AS-TP RUN (19-Aug-2026)

### Built (`build/p1-25/app/`)

- Added `tp_fidelity.py`, a deterministic read-only DOCX validator. It does not
  generate, rewrite or restyle Proposal Builder output.
- Enforced `Proposed BOQ -> Commercials -> Acceptance`, required BOQ and
  commercial tables, exact customer-selling facts, approved RAG provenance,
  prohibited internal commercial labels and the golden 16-inline-shape floor.
- Added an approved customer-commercial contract derived from a controlled
  costing sheet. Customer TP generation now rejects raw/internal cost, buy
  price, margin and markup fields and validates line, subtotal, VAT and total
  arithmetic before calling Builder.
- Failed Builder validation is persisted with the returned artifact and moves
  the build/proposal to `QUARANTINED`; P1-22 release remains fail-closed.
- No Proposal Builder or Local LLM source/runtime configuration was modified.

### Acceptance evidence

| Check | Result |
|---|---|
| Focused P1-19/P1-20 suite | **20 passed** |
| PostgreSQL handoff/quarantine suite | **3 passed** |
| Full PostgreSQL 16/pgvector suite | **85 run: 83 passed, 2 opt-in live tests skipped** |
| Opt-in frozen Builder CP/TP/AMC transport test | **1 passed under the former expected-quarantine assertion** |
| Live TP DOCX | **1,533,210 bytes**, SHA-256 `13d4af9773b3277543f51b234d806d7b98ffd8f375916844a40d9019e706494c` |
| Required section order | **Passed**; Commercials immediately follows Proposed BOQ |
| Selling facts / internal-label leakage | **Passed** |
| Golden inline-shape floor | **Failed: 3 actual / 16 required** |
| Word render inspection | **Failed: 9 pages vs 26-page golden; nested synthetic CP, TOC and layout drift** |
| Final build state | **QUARANTINED** |

### Decision / next task

P1-20 was not accepted for production. This run proved fail-closed quarantine,
but its CP-as-TP input was not valid vendor-TP fidelity evidence. The corrected
20-Aug run above supersedes its fidelity conclusion. P1-21 is not a remedy for
missing Builder content and remains conditional.

---

## P1-19 - Live existing Proposal Builder transport - PASSED (18-Aug-2026)

### Built (`build/p1-25/app/`)

- Added an Orchestrator adapter for the frozen Builder's existing authenticated
  synchronous API; no Builder source or runtime configuration was changed.
- CP and NationLabs-owned AMC use the existing `/api/generate` route.
- TP uses the existing `/api/generate-tp-vendor` multipart route and requires a
  source PDF/DOCX from a configured controlled local artifact root.
- TP source artifact path, type, size and SHA-256 are validated before upload.
- Returned DOCX files and metadata are atomically archived in the
  `proposal-artifacts` Docker volume with payload and artifact hashes.
- Added `existing_sync`/`v1_async` transport selection and the read-only
  `/integrations/proposal-builder/build-health` endpoint.
- Added offline contract/security tests and an opt-in live CP/TP/AMC acceptance
  test. Credentials remain only in the ignored `.env` file.

### Acceptance evidence

| Check | Result |
|---|---|
| Focused P1-19 adapter/proposal suite | **14 passed** |
| Live frozen Builder CP/TP/AMC test | **1 passed** |
| Full suite with disposable PostgreSQL + live Ollama + live Builder | **78 passed, 0 failed** |
| Live CP DOCX | **438,597 bytes**, SHA-256 verified |
| Live TP DOCX | **1,533,210 bytes**, source and result SHA-256 verified |
| Live AMC DOCX | **293,064 bytes**, SHA-256 verified |
| Runtime health | API healthy; Builder `UAT`, transport `existing_sync` |
| Frozen-system boundary | No Local LLM or Proposal Builder source/configuration changed |

### Remaining gates

- Corrected on 20-Aug: genuine vendor input reaches the TP endpoint and the
  output is archived, but P1-20 still quarantines it for missing golden objects.
- The synchronous Builder returns DOCX only. The P1-22 release package remains
  fail-closed until the required final PDF artifact is available and hashed.
- P1-21 is conditional on a compliant Builder DOCX plus a confirmed automatic
  PDF requirement.

---

## P1-14 - Historical evaluation dataset tooling - TOOLING PASSED (14-Aug-2026)

### Built (`build/p1-25/app/`)

- `historical_dataset.py` - idempotent 30-50 deal collection-folder generator,
  strict workbook/schema/artifact validator, coverage analysis and JSON
  completeness-report writer.
- `dataset_pack/labels-template.xlsx` - reviewed workbook with `Deals`,
  `Requirement Truth`, `Quote Truth`, `Security Cases`, instructions and
  controlled lists. Human-validation metadata and row readiness are visible.
- `dataset_pack/README.md` - air-gapped collection and validation procedure.
- `tests/test_p114_historical_dataset.py` - synthetic 30-deal acceptance,
  no-overwrite/idempotency and fail-closed incomplete-data tests.
- Real owner evidence remains local-only: `local-historical-dataset/` is
  excluded from Git and the Docker build context.

### Acceptance evidence

| Check | Result |
|---|---|
| P1-14 focused suite | **3 passed** |
| Synthetic acceptance dataset | **30/30 complete**, all target-mix checks passed |
| Fail-closed regression | Missing quote artifact + `DRAFT` review state produced **29/30**, sign-off false |
| Full PostgreSQL 16/pgvector suite | **71 tests run: 70 passed, 1 opt-in live-Ollama test skipped** |
| Offline image regression suite | **71 tests run, 15 environment-dependent skips** |
| Compose render | **Passed** with `.env.example` |
| Frozen-system boundary | No Local LLM or Proposal Builder source/configuration changed |

The disposable PostgreSQL container, isolated network and test image were
removed after validation. The workbook was inspected for formula errors and
all six sheets were rendered for visual verification.

### Remaining owner gate

P1-14 is not fully accepted and P1-24 remains blocked until Raghu supplies at
least 30 real historical deals and a second presales reviewer validates the
labels. No synthetic data may be used for the production model go/no-go.

The production-server UAT deployment is also deferred. The current Hyper-V host
had only 4.1 GB available RAM, so UAT remains local until the application is
production-ready and dedicated VM capacity is approved.

---

## P1-OPS-UAT-PREP - Production-server UAT preparation (14-Aug-2026)

### Built / changed

- `build/p1-25/app/docker-compose.yml` now supports production `.env` overrides
  for:
  - `ORCHESTRATOR_HTTP_PORT`
  - `PG_HOST`
  - `PG_PORT`
  - `PG_DATABASE`
  - `OLLAMA_URL`
- `build/p1-25/app/.env.example` now documents the production-safe placeholders
  for PostgreSQL, Orchestrator port, Ollama and Proposal Builder build URL.
- `docs/Orchestrator-Production-UAT-Runbook.md` added with the internal UAT
  topology, `.env` checklist, start commands, smoke checks, rollback and
  production-live gates.
- `RUNBOOK.md`, `CURRENT-STATE.md` and `BACKLOG.md` updated to point to the UAT
  runbook and preserve the external-input gates.

### Validation evidence

| Check | Result |
|---|---|
| Docker Compose render with `.env.example` | **Passed** |
| Container regression tests | **68 passed, 15 skipped** via `python -m unittest discover -s tests` |
| Frozen-system boundary | No Local LLM or Proposal Builder source modified |

### Notes

- This is deployment preparation, not production-live sign-off.
- The package can later deploy under `192.168.71.2` with `OLLAMA_URL` set to the
  approved internal Ollama endpoint. Actual deployment is now held because the
  host had only 4.1 GB available RAM; local Docker remains the current UAT.
- Business-live remains blocked by Proposal Builder build output availability,
  the real P1-14 benchmark dataset/P1-24 go-no-go, and production operations
  validation such as backup/restore and security tooling.

---

## P1-25 - Security hardening - PASSED, Orchestrator controls (12-Aug-2026)

### Built (`build/p1-25/app/`)

- `security.py` - local file signature/active-content screening, prompt-injection
  regression detection, RBAC policy helpers, security event persistence and
  restore-verification evidence.
- FastAPI endpoints for file scan, prompt-injection check, RBAC check,
  restore-verification recording and security event listing.
- Security tables for `security_events`, `rbac_roles` and
  `restore_verifications`, all linked through audit events.
- Secrets-hygiene regression check for the active snapshot.

### Acceptance evidence

| Test | Result |
|---|---|
| Pure P1-25 security tests | **5 passed** |
| Live P1-25 Postgres security test | **1 passed** against disposable PostgreSQL 16 + pgvector |
| Full P1-15-P1-25 snapshot suite | **56 passed, 15 skipped** against disposable PostgreSQL 16 + pgvector |
| File security | active PDF content, bad extension and magic mismatch quarantine locally |
| Prompt-injection regression | common instruction-override/secret-exfiltration phrases flagged |
| RBAC/restore/audit | policy checks, restore evidence and security audit events persisted |
| Secrets hygiene | active snapshot has no committed `.env` or obvious token/private-key markers |

Temporary Docker test database was removed after testing. No cloud/SaaS scanner,
Proposal Builder or Local LLM implementation/configuration was changed.

### Remaining gated work

All currently actionable Orchestrator P1 implementation items are complete
through P1-25. P1-20/P1-21 require frozen Proposal Builder build output, and
P1-24 requires the real P1-14 labelled historical dataset benchmark run.
Production operations still need target-server validation for ClamAV/Wazuh/full
isolated restore drills before production sign-off.

---
## P1-23 - Benchmark harness - PASSED, harness ready (12-Aug-2026)

### Built (`build/p1-23/app/`)

- `benchmarks.py` - local dataset validation, deterministic case metrics,
  report summaries, Postgres persistence and audit events.
- Dataset/run/case-result tables for `evaluation_dataset/test/result` style
  evidence.
- FastAPI endpoints for `POST /benchmarks/run` and `GET /benchmarks/runs`.
- Sample labelled fixture covering requirement extraction, classification,
  vendor-response classification and quote extraction.

### Acceptance evidence

| Test | Result |
|---|---|
| Pure P1-23 benchmark tests | **4 passed** |
| Live P1-23 Postgres benchmark test | **1 passed** against disposable PostgreSQL 16 + pgvector |
| Full P1-15-P1-23 snapshot suite | **51 passed, 14 skipped** against disposable PostgreSQL 16 + pgvector |
| Automatic report | generated and persisted with dataset hash, metrics, case results and audit event |
| Sign-off gating | sample dataset returns `INSUFFICIENT_DATA` until 30+ real labelled cases exist |

Temporary Docker test database was removed after testing. No cloud AI/SaaS,
Proposal Builder or Local LLM implementation/configuration was changed.

### Next task

P1-24 model go/no-go remains blocked until the real P1-14 30-50 labelled
historical dataset is available and run through the harness. P1-20/P1-21 remain
blocked/deferred until Builder output is available. The next actionable open item
is **P1-25 - Security hardening**, unless those missing inputs arrive first.

---
## P1-22 - Proposal release flow - PASSED (12-Aug-2026)

### Built (`build/p1-22/app/`)

- Release-package schema for final approval/artifact snapshots and deterministic
  package hashes.
- Human-controlled submission recording with method, recipient, evidence ref,
  evidence SHA-256, submitted-by and recorded-by fields.
- FastAPI endpoints for release package preparation, submission recording and
  release package lookup.
- Release gates require completed document build, passing validation, final
  DOCX/PDF artifacts and SHA-256 hashes, approved proposal-value approval and
  satisfied Deal Registration state.

### Acceptance evidence

| Test | Result |
|---|---|
| Pure P1-22 API/boundary tests | **2 passed** |
| Live P1-22 Postgres release tests | **2 passed** against disposable PostgreSQL 16 + pgvector |
| Full P1-15-P1-22 snapshot suite | **47 passed, 13 skipped** against disposable PostgreSQL 16 + pgvector |
| Release gates | blocked when final PDF artifact was missing |
| Submission control | recorded human submission evidence; no external send path exists |
| Audit lineage | release package and customer submission audit actions recorded |

Temporary Docker test database was removed after testing. No Proposal Builder or
Local LLM implementation/configuration was changed.

### Next task

P1-20 and P1-21 remain blocked/deferred until frozen Proposal Builder build
output is available. The next actionable open engineering item is **P1-23 -
Benchmark harness**, unless the Builder endpoint is supplied first. P1-14 remains
a parallel owner/data activity.

---
## P1-19 - Proposal Builder handoff - PASSED, Orchestrator foundation (12-Aug-2026)

### Built (`build/p1-19/app/`)

- `proposals.py` - Orchestrator-owned proposal payload freeze, precondition
  gates, proposal/version tables, document build job attempts, retry state,
  artifact SHA-256 tracking, validation-result storage and proposal audit links.
- Existing Proposal Builder HTTP adapter extended with the documented
  `/api/v1/builds`, `/api/v1/builds/validate`, `/api/v1/builds/{id}` and
  `/api/v1/builds/{id}/artifacts` contract methods.
- FastAPI endpoints added for proposal assemble, build submit, build refresh and
  artifact lookup.
- `PROPOSAL_BUILDER_BUILD_URL` added as an optional build-contract endpoint.
  If unset, the adapter falls back to `PROPOSAL_BUILDER_URL`.

### Acceptance evidence

| Test | Result |
|---|---|
| Pure Builder v1 contract tests | **8 passed** |
| Live Orchestrator Postgres handoff tests | **2 passed** against disposable PostgreSQL 16 + pgvector |
| Full P1-15-P1-19 snapshot suite | **45 passed, 11 skipped** against disposable PostgreSQL 16 + pgvector |
| Payload freeze | selected quote commercial totals remained unchanged in Builder handoff payload |
| Preconditions | accepted quote, validation, approval and Deal Registration gates enforced |
| Job/artifact audit | build ref, retry attempts, returned artifact refs/SHA-256 hashes and audit actions recorded |

Live CP completion remains blocked until the external frozen Proposal Builder
exposes the documented `/api/v1/builds` endpoint. The passed tests use a fake
documented Builder adapter and do not modify or copy Proposal Builder source.

Temporary Docker test database was removed after testing. No Local LLM
implementation/configuration was changed.

### Next task

**P1-20 - TP golden-fidelity gate**, once Builder build output is available for
validation. If `/api/v1/builds` remains unavailable, resolve that external
integration blocker first. P1-14 historical dataset collection remains a
parallel owner/data activity.

---
## P1-18 — Multi-vendor / multi-quote comparison — ✅ PASSED (12-Aug-2026)

### Built (`build/p1-18/app/`)

- `quote_comparison.py` — deterministic `Decimal` AED normalization, canonical
  result serialization/hash, recorded exchange-rate provenance, immutable
  comparison runs and human-selected quote/version freeze.
- PostgreSQL comparison inputs retain exact quote/version/validation/rate ids;
  selection decisions preserve every selected and non-selected candidate.
- FastAPI endpoints record exchange rates, create/list comparison runs and
  select/read the active quote selection.
- Selection permits commercial work while Deal Registration is pending but marks
  the downstream proposal gate ineligible until that vendor path is satisfied.

### Acceptance evidence

| Test | Result |
|---|---|
| Three-vendor native/AED matrix | passed; AED, USD and EUR totals retained and normalized from recorded rates |
| Repeatability | same inputs in different order produced byte-identical `result_json` and hash |
| Revision history | superseded v1 retained; only current validated v2 selected |
| Human selection | selected version/snapshot/actor/reason/time preserved; non-selected decisions recorded |
| Deal Registration | pending vendor can be compared/selected but remains `proposal_eligible=false` |
| Deterministic boundary | no LLM and no exchange-rate network lookup in comparison service |
| Full P1-15–P1-18 suite | **46 passed** against disposable PostgreSQL 16 + pgvector |
| Compose/image/secrets | configuration and image-secret checks passed; configured secret scan passed |

Temporary Docker test database, network and image were removed after testing.
No Proposal Builder or Local LLM implementation/configuration was changed.

### Next task

**P1-19 — Proposal Builder handoff.** P1-14 historical dataset collection
remains a parallel owner/data activity.

---

## P1-16 — Deterministic quote validation — ✅ PASSED (11-Aug-2026)

### Implemented (`build/p1-16/app/`)

- `quote_validation.py` — pure standard-library `Decimal` engine for quantity ×
  unit price, line totals, subtotal, VAT, grand total, currency confirmation and
  policy-required validity/payment/delivery terms.
- `quotes.py` — additive validation status/history schema, claims/policy
  snapshots, computed values, mismatch review routing and append-only audit.
- `POST /quotes/{quote_id}/validate` and `GET /quotes/{quote_id}/validation`.
- review board visibility for open quote-validation discrepancies.
- server-controlled environment policy for tolerance, currency confirmation,
  stated totals, VAT and required terms.

The Orchestrator compares vendor claims and records discrepancies. It never
auto-corrects vendor figures. No Local LLM, Proposal Builder implementation or
cloud/SaaS dependency is present in the validation engine.

### Acceptance evidence

| Test | Result |
|---|---|
| Pure deterministic P1-16 tests | 5 passed |
| Seeded arithmetic-error repeatability | blocked 20/20 runs |
| Live valid quote | `VALIDATED`; AED 28,500.00 + AED 1,425.00 VAT = AED 29,925.00 |
| Live error quote, repeated | `BLOCKED` both runs; same review; two audit events |
| Vendor-claim immutability | passed; seeded wrong line total remained unchanged |
| Human-review/API/UI visibility | passed |
| Full P1-10/P1-12/P1-15/P1-16 suite | **27 passed** |
| Compose configuration | passed |
| Built-image secret check | passed; `/srv/app/.env` absent |

The live suite used disposable `pgvector/pgvector:pg16`, the committed P1-02
audit schema and the `orchestrator_app` ownership model. Test resources were
removed after acceptance. Frozen external systems were not modified.

---

## P1-15 — Quote lifecycle / Proposal Builder adapter — ✅ PASSED (11-Aug-2026)

### Implemented (`build/p1-15/app/`)

- `integrations/proposal_builder/` — typed HTTP boundary around the frozen
  builder's existing session-authenticated `/api/extract-quote` endpoint.
- `quote_lifecycle.py` — content-addressed source archival before adapter use,
  SHA-256 provenance, idempotent ingest and no-silent-drop failure handling.
- `quotes.py` — PostgreSQL vendor-response provenance, quote groups/revisions,
  current-version uniqueness, line items, ingestion attempts and
  `FAILED_REVIEW` queue.
- API routes for quote upload/listing, review queue and builder health.
- quote ingestion deliberately remains allowed while Deal Registration is
  pending; proposal generation/release retains the later DR gate.
- Proposal Builder URL/user/password are environment-only; no credential was
  committed and no Proposal Builder source was changed.
- `.dockerignore` excludes `.env`/`.env.*` from the Docker build context; the
  built image was inspected and contained no `/srv/app/.env`.

### Test evidence

| Test | Result |
|---|---|
| Offline adapter/schema/lifecycle suite | 14 passed; live DB test skipped as designed |
| PostgreSQL 16 + pgvector live P1-15 suite | 15 passed |
| Full active suite (P1-15 + P1-10/P1-12 regressions) | **18 passed** |
| Compose configuration | passed |
| P1-15 Python syntax parse | 21 files passed |
| Built-image secret check | passed; `/srv/app/.env` absent |
| Approved live Proposal Builder authentication | passed |
| Live Builder quote extraction | passed; 5 normalized AED line items |
| Live archive/provenance/persistence/audit/idempotency/DR assertions | passed |

The live suites used an exact disposable `pgvector/pgvector:pg16` container
initialized with the committed P1-02 audit schema. The final live contract used
the frozen Builder's read-only synthetic wrapped-quote fixture and an approved
service account. It verified raw byte preservation, matching SHA-256, structured
PostgreSQL storage, quote version 1, two quote audit events, identical-source
idempotency and continued quote work in `BLOCKED_PENDING_DEAL_REG` state.

No Proposal Builder or Local LLM source/configuration was modified.

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

- **I-04:** `.env` placeholder pasted literally (twice) → password reset to a temporary build password. ⚠️ **Security task remains: rotate before production** because the historical value appeared in chat and Git history.
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

**P1-08 + P1-09 — Vendor service, deal-reg gate, RFQ drafting — ✅ PASSED (08-Aug-2026)**

### Test subject: REAL client RFP (SOC tooling BOQ, scanned WhatsApp image, 9 items / 7 vendors) — transcribed and submitted as NL-OPP-2026-0003.

### Built (`build/p1-09/app/`, commits 563b8d7/b836425)

- `vendors.py` — vendors + deal_registrations + rfqs tables; 8-vendor demo seed (6 OEMs + 2 distributors, matching the real RFP's vendor set); keyword/domain matching; **fail-closed `deal_reg_capable`** (blank = false)
- `rfq.py` — the gates, enforced in code: BLOCKED_PENDING_DEAL_REG for OEM/deal-reg-capable distis until DR approved; end-user disclosure only for OEM/Distributor tier + recorded human approval; human-triggered send; idempotency keys on create + send
- `main.py` — endpoints + clean 403/400 gate refusals (fix: were bare 500s)

### Acceptance evidence (live)

| Test | Result |
|---|---|
| RFQ creation on real RFP | 8 RFQs: CIS → DRAFT (no DR needed); 7 → **BLOCKED_PENDING_DEAL_REG** ✅ |
| Deal-reg approval (Fortinet, ref FORT-DR-2026-8841) | Unblocked → qwen3:14b drafted professional RFQ **with deal-registration paragraph** ✅ |
| Disclosure gate | Send refused without recorded approval; after `approver: raghu` recorded → allowed ✅ |
| Human send + double-click | First `SENT`; second `already sent (idempotent)` ✅ |
| Blocked send attempt (CrowdStrike) | Clean `403 FORBIDDEN: deal registration not approved` ✅ |
| Duplicate creation | Re-run: all 8 "already exists (idempotent)", zero new rows ✅ |

### Observations logged

- Draft body is generic when extraction lacks buyer contact/end-user (0003 had none — correct behavior; placeholder-driven). Prompt enrichment from full BOQ line items = P1-09b polish item.
- Real vendor-master Excel (A-5.1) still required from Raghu to replace demo seed.

**P1-10 + P1-12 — Follow-up engine + ported regression tests — ✅ PASSED (08-Aug-2026)**

### Built (`build/p1-10/app/`, commits f377567/d5dee33)

- `followup.py` — daily tick: stop-on-response, escalation after 3 nudges, ≥20h gap; **template-based nudges** (zero tokens — LLM reserved for thinking tasks); driven by host cron `08:07 daily` (reboot-persistent, no daemon)
- `tests/test_followup.py` — the prototype's 3 failing regressions ported and GREEN: stop-on-quote, escalate-after-limit, **no-followups-before-send** (the deal-reg regression is now structural)

### Acceptance evidence (live)

| Test | Result |
|---|---|
| Ported regression tests | **3/3 passed** (vs 3 FAILED in old prototype) ✅ |
| Live tick on real Fortinet RFQ | 20h-gap rule → nudge #1 fired after aging → response recorded → cadence stopped + RESPONSE_RECEIVED alert ✅ |
| Escalation | Internal alert to assigned NL owner after limit ✅ |
| Cron | `7 8 * * * curl -X POST localhost:8080/followups/run` installed ✅ |

### Issues hit & fixed

- **I-07 (test isolation):** pytest ticks processed ALL SENT RFQs → 3 phantom follow-ups + premature escalation on the real Fortinet RFQ. Fixed with `only_refs` scoping; phantom rows cleaned; re-verified: 3/3 passed with **0** production leakage. Lesson logged: global-effect functions need scope parameters from day one.

**P1-11 — Approval engine — ✅ PASSED (08-Aug-2026)**

### Built (`build/p1-11/app/approvals.py`, commit a7b2659)

- `approval_rules` config table — thresholds as DATA, not code; provisional seed marked `PROVISIONAL-*` until Worksheet AM-1 is signed (flip with one UPDATE)
- `approvals` table — PENDING→APPROVED/REJECTED with actor+timestamp; idempotent routing
- Gap safety: amount outside all rules → engine **refuses** (`no approval rule covers X AED`) instead of misrouting

### Acceptance evidence (live)

| Test | Result |
|---|---|
| 45,000 AED | → FINAL_VERIFIER via AM-R1 ✅ |
| 200,001 AED (the criterion) | → FINANCE via AM-R3 ✅ |
| Idempotency | Double-submit → "already pending" ✅ |
| Config-driven (no redeploy) | SQL UPDATE changed routing immediately ✅ |
| Matrix gap (AM-R2 ceiling → 100K) | 150K refused: `no approval rule covers 150000.0 AED` ✅ |
| Decision + audit | APPROVED by raghu, `approval_approved` hash-chained ✅ |

### Notes

- My initial T3 scenario was mis-specified (broke AM-R3's range instead of creating a gap) — caught, corrected, and it surfaced the gap-refusal feature as a bonus acceptance test. Matrix restored to clean provisional state.
- **Owner input still needed:** signed AM-1 worksheet → flip `source` to SIGNED-AM1 (Niren/Finance).

**P1-13 — Human-in-loop review UI + file intake — ✅ PASSED (08-Aug-2026)**

### Built (`build/p1-13/app/`, commits bea20d3/97cb6f6/5783d34)

- `static/index.html` — three-column review board (vanilla JS, zero build chain): intake (paste text **or upload file**) · opportunity pipeline · extraction/classification view · inline clarification answering · RFQ/deal-reg board with gated buttons (Approve Deal Reg / Approve Disclosure / Send) · approvals inbox · alerts feed · LLM token meter
- `intake_files.py` — PDF (pdfplumber + tesseract fallback for scans) / XLSX / CSV / DOCX / image OCR; originals preserved byte-for-byte in the `rfp-archive` Docker volume, SHA-256 provenance columns on opportunities

### Acceptance evidence (live)

| Test | Result |
|---|---|
| UI board | All three columns live against proven endpoints ✅ |
| **Real client RFP screenshot uploaded through browser** | `NL-OPP-2026-0004 → CLARIFICATION_REQUIRED (tesseract, 1091 chars)` — OCR → qwen3:14b → pipeline, honest clarification halt (no customer metadata in image) ✅ |
| Provenance | `source_channel=upload:.png`, `extraction_method=tesseract`, filename + SHA-256 recorded ✅ |
| Issues | I-08: pdfplumber pin typo (1.4.3→0.11.5) — fixed, rebuilt |

### Phase 1 status after P1-13

P1-A ✅ · P1-B ✅ · P1-13 ✅ → remaining: P1-C quotes/RAG (P1-14→18), P1-D proposals (P1-19→22), P1-E benchmarks/security (P1-23→25). Owner inputs pending: real vendor Excel, signed AM-1, 30–50 historical deals, golden AMC confirmation.

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

**P1-17 — Approved-content pgvector RAG + queued grounded drafting — ✅ PASSED (12-Aug-2026)**

### Built (`build/p1-17/app/`)

- `knowledge.py` — PostgreSQL/pgvector document, chunk, embedding, retrieval,
  draft-job and citation persistence; explicit approval/security/validity/scope
  controls; HNSW + full-text hybrid retrieval; retrieval and transition audit.
- `integrations/ollama/` — air-gapped Ollama adapter for `bge-m3` embeddings
  and schema-constrained grounded `qwen3:14b` drafting.
- `rag_drafting.py` / `rag_worker.py` — accepted validated quote facts remain
  a separate authority from untrusted RAG language; generation is queue-only
  and consumed by one worker.
- FastAPI endpoints for document ingestion, human approval, approved retrieval,
  retrieval history, draft enqueue and job status.
- Compose configuration for one RAG worker and local model settings; no cloud
  dependency or external-system implementation copied into the Orchestrator.

### Acceptance evidence

| Test | Result |
|---|---|
| Full P1-15/P1-16/P1-17 suite against disposable PostgreSQL 16 + pgvector | **40 passed** |
| Approval/security/status/expiry/scope SQL prefilter | Only approved, cleared, in-scope content returned |
| Hostile indirect-prompt content | Ingested `FLAGGED`; approval structurally refused |
| Chunking | 600-word target, 90-word overlap; pricing rows atomic; repeated section provenance retained |
| Citations/audit | document/version/status/section/page/source/hash/date/owner/score persisted; retrieval audited |
| Commercial hallucination tripwire | Accepted `VALIDATED` quote facts passed separately; RAG supplies language only |
| Queue boundary | API only enqueues; worker claims with `FOR UPDATE SKIP LOCKED` |
| Live Local LLM adapter | `bge-m3` returned 1,024 dimensions; `qwen3:14b` returned grounded JSON using `[K1]` |
| Compose/image security | Compose config valid; `/srv/app/.env` absent from image |

### Operational notes

- The administrator installed the official `bge-m3:latest` model on the frozen
  Ollama service at `192.168.71.11`; the Orchestrator implementation itself did
  not modify Local LLM configuration or Proposal Builder source.
- The live smoke test uses synthetic approved language and synthetic validated
  commercial facts. Production knowledge still requires separately authored
  and human-approved source documents.
- The physical Hyper-V host is `192.168.71.2`; the approved interim application,
  PostgreSQL and local-model topology is the `aiinference` VM at `192.168.71.11`.

### Next task

**P1-18 — Multi-vendor / multi-quote comparison.** P1-14 historical dataset
collection remains a parallel owner/data activity.

---

## History — P1-01 blocked period (07-Aug, resolved 08-Aug)

- Off-site laptop (10.212.134.200) had no route to the air-gapped 192.168.71.x segment; execution shifted to guided mode (Raghu's hands, Kimi's commands) — kept as the working pattern for VM-side tasks.
- Artifacts from the blocked period retained for reuse: `build/p1-01/vm-validate.sh` (generic acceptance checker — RAM threshold updated to 36 GiB), `build/p1-01/vm-resize-hyperv.ps1` (reference runbook; actual resize was done interactively).

---

**P1-20 remediation — source-aware TP validation v2 — ✅ CODE/TEST PASSED, LIVE RE-ACCEPTANCE PENDING (26-Aug-2026)**

### Built (`build/p1-25/app/`)

- Existing Proposal Builder adapter now requires an auditable TP customer
  identity contract and maps the masked code, real name, aliases and masking
  flag to the frozen Builder's existing multipart API fields.
- Returned DOCX validation scans all Word XML stories for surviving aliases
  without echoing the protected names into validation logs.
- Exact commercial comparison now parses rendered numbers as `Decimal` values,
  allowing display separators such as `120,000.00` while preserving equality.
- The invalid global 16-inline-shape floor was removed. The v2 gate verifies
  image relationship integrity, rejects broken/corrupt/large blank media, and
  compares detected source PDF/DOCX graphics with drawings in the main document
  story so template header/footer logos cannot satisfy preservation.
- The Builder remains frozen and the Orchestrator never edits generated DOCX.

### Acceptance evidence

| Test | Result |
|---|---|
| Focused P1-19/P1-20 adapter and fidelity tests | **20 passed** |
| P1-19 through P1-22 offline regression suite | **42 passed, 1 expected live skip** |
| Complete active image against disposable PostgreSQL 16/pgvector + P1-02 audit schema | **109 passed, 2 expected opt-in live skips** |
| Missing client masking contract | Rejected before Builder call |
| Alias surviving in DOCX | `masked_client_identity` fails closed |
| Formatted money | Exact numeric facts pass without string-format false negative |
| Source graphic loss / missing source evidence | Quarantined |
| Broken DOCX media target | Rejected as invalid package |

### Still required

- Regenerate the genuine vendor TP through this revised Orchestrator contract.
- Obtain a passing `p1-20.tp-source-aware.v2` report.
- Complete page-by-page human visual approval, including distributor identity,
  split-table and final BOQ/commercial/acceptance review.
- Do not release the previously reviewed unmasked Builder artifact.
