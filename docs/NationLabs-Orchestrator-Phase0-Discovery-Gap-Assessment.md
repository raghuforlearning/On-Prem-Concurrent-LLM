# NationLabs AI Presales Orchestrator — Phase 0: Current-State Discovery & Gap Assessment

**Version:** 1.0
**Date:** 06-Aug-2026
**Author:** Kimi (for Raghu)
**Basis:** Architecture v2.0 (05-Aug-2026), approval decisions of 06-Aug-2026
**Method:** Direct inspection of local artifacts (workspace + `C:\NL\proposal-builder` + VM console transcripts). Every finding below is marked **[VERIFIED]** (inspected this session), **[STALE]** (known earlier, not re-verifiable now), or **[MISSING]** (required input not yet provided).

---

## 0. Decision Recap (from your 06-Aug approval)

**Approved (13):** FastAPI modular monolith MVP · PostgreSQL 16 · pgvector · LangGraph + Postgres checkpoints · Ollama initially · existing proposal builder reused as a service · dedicated Windows document-worker concept · human-controlled external sending · deterministic commercial calculations · configurable approval matrix · local RAG with approved-content filtering · two-VM MVP structure · benchmark-gated model selection.

**Not yet approved (8) — treated as open constraints throughout this document:**

| # | Deferred item | Phase 0/1 implication |
|---|---|---|
| D1 | Final Windows Server + Office implementation | Document-worker built to concept; licensing/procurement stays open |
| D2 | Final model selection | qwen3:14b / gemma3:4b are *candidates*; benchmark gate in Phase 1 |
| D3 | Final approval thresholds | Worksheet in §6 must be signed off; code uses config, not constants |
| D4 | Final AMC workflow | AMC handled only at data-model level in Phase 1; workflow deferred |
| D5 | "Immutable storage" claim | Language corrected to **append-only audit log + hash-chained records**; no WORM/immutability claim is made anywhere |
| D6 | Production co-location of DB and inference | Phase 1 MVP: PostgreSQL runs on AI VM (interim). Target topology kept in diagrams; flagged as open risk R-1 |
| D7 | Final malware-control sufficiency | ClamAV pipeline specified; sufficiency review deferred to security sign-off |
| D8 | Final deployment schedule | Roadmap expressed in person-weeks only; no calendar commitments |

---

## 1. P0.1 — Existing Proposal-Builder Source & Capability Inventory

### 1.1 What actually exists — two separate builder tracks

**Track A — `C:\NL\proposal-builder` (Node.js, v2.3.0) [VERIFIED]**

The strategic asset. A deterministic, Express-based document-generation service — package description literally reads *"deterministic document generation, no AI"*.

| Area | Evidence | Capability |
|---|---|---|
| CP generation | `src/generate-cp.js`, `templates/template-spec.json` | Generates CP from spec; spec JSON pins **immutable parts by SHA-256** (`word/footer1.xml`, `header1.xml`, `styles.xml`, `numbering.xml`) — this is exactly Niren's zero-deviation requirement, already engineered |
| TP generation | `src/generate-tp.js`, `templates/tp-spec.json`, `tp-content-library.json`, `tp-fragments.json`, `tp-structure.json` | Structured TP with reusable content library |
| AMC generation | `src/generate-amc.js`, `templates/amc-spec.json` | **AMC generator already exists** ("Track 1 — reference doc generated 26-Jul-2026 from THAG-derived v2 markup") |
| Quote intake | `src/quote-email.js`, `quote-pdf-parse.js`, `quote-image-parse.js`, `quote-table-parse.js`, `quote-reconcile.js`, `quote-router.js`, `quote-completeness.js`, `quote-html-table.js` | A **full vendor-quote parsing pipeline**: email (.msg via msgreader), PDF, image, HTML table, RTF — with reconciliation and completeness checking. This directly serves workflow steps 20–28 |
| Costing | `src/generate-costing.js`, `src/assumptions.js`, `assumptions-exclusions.json` | Deterministic costing + assumptions/exclusions engine |
| Runtime | `package.json` | Express 4, `docx` 8.5 (pure-JS docx — **no Word needed to generate**), mammoth, pdf-parse, xlsx, helmet, rate-limit, bcryptjs (has auth hardening already) |
| Tests | `test/` — `run-all.js`, `test-cp-e2e.js`, `test-amc-e2e.js`, `test-amc-vendor-e2e.js`, `test-boq-arithmetic.js`, `test-boq-rows.js`, `test-assumptions.js`, `test-delivery-headers.js` + fixtures | E2E coverage incl. BOQ arithmetic |
| Governance docs | BRD v1.0, Functional Spec v1.0, Release Doc, Runbook, Deployment Plan, Remediation Plan, Format Audit Report, CP How-It-Works v1.0 | Formal documentation already exists — Phase 1 should read these before touching code |

**Track B — `proposal-templates\build_exact_cp.py` (Python + Word COM) [VERIFIED]**

My golden-mirror prototype (111 lines): copies `golden-cp.docx`, positional Word find/replace, Excel `Range.Copy` → Word `PasteSpecial` for BOQ/costing tables as EMF images. Output visually verified correct (`EXACT-CP-ENOC-NL-PP-AN-016-26.docx/.pdf`). Supporting: `fill_golden.py` (206), `table_image.py` (75).

### 1.2 Assessment

- **Track A is the reuse target** mandated by v2.0 §11 — it runs on Ubuntu (no Office needed for generation), has tests, immutable-part hashing, and already covers CP/TP/AMC + quote parsing.
- **Track B's unique value** is *rendering fidelity*: Word-COM paste of Excel ranges produces pixel-faithful BOQ tables, and Word is required for authoritative PDF export. This maps to the **Windows document-worker** role — final render + PDF + visual regression, not generation.
- **Convergence risk R-2:** two tracks could drift. Recommendation: Track A = generation engine; Track B technique migrates into the document-worker for final Word render/PDF/visual diff. One builder, one renderer.
- **Gap G-1:** `build_exact_tp.py` was never written — but Track A's `generate-tp.js` may already make it unnecessary. **Action:** Phase 1 task to diff Track A TP output vs `golden-tp.docx` before deciding.

---

## 2. P0.2 — Existing Kimi Prototype Source & Database Inventory

**Location:** `nationlabs-orchestrator\` — **[VERIFIED this session]**

### 2.1 Source (2,368 LOC Python, Flask + SQLite)

| Module | Lines | Role | Reuse verdict |
|---|---|---|---|
| `services/intake.py` | 180 | RFP intake, archive, readiness scoring | Logic → FastAPI intake module |
| `services/analysis.py` | 235 | Ollama extraction + classification, JSON retry | Prompts + retry logic → LangGraph nodes |
| `services/vendor.py` | 104 | Vendor matching from Excel | → vendor-master service (DB-backed) |
| `services/comms.py` | 157 | RFQ drafting, end-user disclosure gate, outbox | Disclosure gate logic is proven — port |
| `services/responses.py` | 167 | Vendor response parsing, alerts | Merge with Track A quote parsers |
| `services/costing.py` | 237 | Deterministic costing checks, tolerance rules | Port rules to calculator service |
| `services/followup.py` + runner | 190 | Daily follow-up state machine, escalation, stop-on-quote | Port to scheduler service |
| `statemachine.py` | 77 | Status transitions | **Replaced by LangGraph** |
| `db.py` | 250 | SQLite layer | **Replaced by PostgreSQL** |
| `audit.py` | 40 | Append-only audit | Port, add hash-chain |
| `prompts/*_v1.py` | 286 | Extraction / classification / quote-response / RFQ prompts | Direct reuse — versioned prompt assets |
| `web/app.py` + templates | 263 + 5 | Demo UI | Rewrite in FastAPI (approved) |

### 2.2 Database (SQLite, 13 tables, live demo data) [VERIFIED]

`opportunities` (16 rows), `rfqs` (6), `vendor_responses` (7), `quotes` (6), `costing_checks` (64), `deal_registrations` (3), `followups` (5), `approvals` (7), `clarifications` (2), `vendors` (2 — demo), `ownership_matrix` (2 — demo), `audit_log` (162), `schema_meta`. Runtime folders prove the flows work: archived RFPs (txt/pdf/png), vendor-email outbox, approval-request outbox, internal alerts, audit logs.

**Migration note:** schema maps cleanly onto the v2.0 50-entity model; demo data is a useful seed/fixture source for Phase 1 tests.

### 2.3 Honest current state — NOT green

- `pytest tests/test_orchestrator.py`: **14 passed, 3 FAILED** [VERIFIED] — `test_followup_stops_on_quote`, `test_followup_escalates_after_limit`, `test_followup_continues_while_deal_reg_pending` (follow-up module regression after the deal-reg feature was added 01-Aug).
- `tests/manual_deterministic_test.py`: collection error (`sqlite3.IntegrityError: FOREIGN KEY`).
- Demo persistence on your desktop relied on a wedged Windows Task Scheduler [STALE — unresolved].

**Verdict:** prototype proved the workflow end-to-end and de-risked prompts/gates, but it is demo-grade. Phase 1 ports its logic; it does not harden this codebase. The 3 failing follow-up tests must be fixed (or the module explicitly ported-and-replaced) so the failing behavior isn't carried into Phase 1 as a hidden assumption — **Backlog item P1-12**.

---

## 3. P0.3 — Current VM, Docker, Ollama & Model Inventory

**Source:** console transcripts `phase0\vm-specs-source.txt`, `phase0\vm-inventory-source.txt` — **[VERIFIED as of 31-Jul-2026 capture; re-verify in Phase 1 kickoff]**

### 3.1 Physical host NLABDLAS01 [STALE — from 19-Jul verification]

Dell PowerEdge R750 · 2× Xeon Silver 4310 (48 logical) · 128 GB RAM · A30 24 GB (PCIe Gen4 x16, ECC, 0 errors) · Windows Server 2019 · 192.168.71.2 · chassis has room for a 2nd double-width GPU.

### 3.2 AI VM `aiinference` @ 192.168.71.11 [VERIFIED from transcript]

| Item | Current | v2.0 sizing recommendation | Gap? |
|---|---|---|---|
| OS | Ubuntu 22.04.5 LTS, kernel 5.15 | Ubuntu 22.04+ | ✅ OK |
| vCPU | **8** | 16–24 | ⚠️ **GAP R-3** — below recommendation |
| RAM | **24 GB** (swap 8 GB, 422 MB used) | 56–72 GB | ⚠️ **GAP R-3** — significantly below |
| Disk | 244 GB, 63 used / 169 free | — | ✅ OK for MVP (model + DB + vector growth to be monitored) |
| GPU | A30 24 GB passthrough, driver 610.43.02, CUDA 13.3, idle, healthy | one A30 sufficient | ✅ OK |
| Note | Host transcript earlier showed driver 529.19/CUDA 12.0 — VM now reports 610.43.02. Record actuals at Phase 1 kickoff. | | ℹ️ |

**Sizing consequence:** with 8 vCPU / 24 GB, the approved MVP (FastAPI + PostgreSQL + LangGraph + Ollama co-located — interim, D6 deferred) will fit *only because inference is queue-serialized* and qwen3:14b + gemma3:4b total ~12.6 GB VRAM. RAM is the binding constraint: Ollama host + Postgres + app + OS in 24 GB leaves little headroom under load. **Recommendation:** raise the VM to 16 vCPU / 48–64 GB at Phase 1 start (host has 128 GB and idle capacity) — cheap insurance, avoids tuning under pressure.

### 3.3 Docker containers [VERIFIED]

| Container | Port | Status | Phase 0 note |
|---|---|---|---|
| `ollama` (ollama/ollama:latest) | 11434 | Up | Inference runtime — approved |
| `guardrails-prod` (serving-guardrails-prod) | 8000 | Up 46 h | **Existing guardrails service — inventory & reuse decision needed (Backlog P1-05)** |
| `guardrails-uat` (serving-guardrails-uat) | 8001 | Up 46 h | Same — UAT twin |

### 3.4 Models [VERIFIED]

| Model | Size | Quant | Context | Capabilities | Status |
|---|---|---|---|---|---|
| `qwen3:14b` | 9.3 GB | Q4_K_M | 40,960 | completion, **tools**, thinking | Candidate primary — benchmark-gated (D2) |
| `gemma3:4b` | 3.3 GB | Q4_K_M | — | completion | Candidate guardrail/light tier |
| `deepseek-r1:32b` | 19.9 GB | Q4_K_M | 131,072 | thinking | **To be removed per your decision** — Backlog P1-04 (frees ~20 GB disk, simplifies MAX_LOADED=2 policy) |

### 3.5 Ollama tuning (already applied) [VERIFIED]

`NUM_PARALLEL=2`, `MAX_LOADED_MODELS=2`, `KEEP_ALIVE=30m`, `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`, `CONTEXT_LENGTH=8192`. **Note:** configured context 8,192 vs qwen3's 40,960 capability — deliberate VRAM thrift; long-document RFPs must be chunked to fit 8k or the limit revisited in benchmarks.

---

## 4. P0.4 — Golden CP / TP / AMC Template Inspection

**Files:** `proposal-templates\golden-cp.docx`, `golden-tp.docx`, `cp-master.docx`, `tp-master.docx` (mirrors of `C:\NL\proposal-builder\templates\`) — **[VERIFIED via python-docx structural scan]**

### 4.1 Structural profile

| Template | Paragraphs | Tables | Inline shapes | ~Words | Sections |
|---|---|---|---|---|---|
| `golden-cp.docx` | 135 | 1 | 2 (BOQ + costing EMFs) | 277 | 1 |
| `golden-tp.docx` | 394 | 3 | **16** | 2,942 | 1 |
| `cp-master.docx` | 129 | 1 | 2 | 153 | 1 |
| `tp-master.docx` | 81 | 1 | 0 | 99 | 1 |

### 4.2 Findings

1. **The golden documents — not the masters — are the format authority.** `tp-master.docx` is a thin skeleton (81 paras, 99 words); `golden-tp.docx` is a full 2,942-word realized proposal with 16 embedded objects. Niren's zero-deviation rule therefore binds to the goldens. Track A already encodes this correctly: `template-spec.json` is `"builtFrom": "templates/golden-cp.docx"` with SHA-256-pinned immutable parts. ✅
2. **CP is simple and already solved twice** (Track A generator + Track B golden-mirror, both verified). Risk: low.
3. **TP is the hard document:** 16 inline shapes (tech tables, figures, signature), 3 tables, long narrative. The TP content library (`tp-content-library.json`, `tp-fragments.json`) is the reusable asset; RAG must draft *language into this structure*, never restructure. **Gap G-1 applies here** — golden-fidelity TP output must be proven against `golden-tp.docx` in Phase 1 (visual regression gate).
4. **AMC golden document: [MISSING].** You never supplied a golden AMC `.docx`. However, Track A has `amc-spec.json` + `generate-amc.js` with a reference AMC generated 26-Jul-2026 from THAG-derived markup, and `test-amc-e2e.js` / `test-amc-vendor-e2e.js` pass-coverage exists. **Action A-4.1:** Niren confirms whether the 26-Jul reference AMC *is* the format authority, or supplies a golden AMC. Until then, AMC workflow stays deferred (consistent with D4) — data model accommodates it, workflow does not ship.
5. Supporting config already inventoried: `disti-names.json`, `assumptions-exclusions.json` — these seed the distributor registry and the assumptions/exclusions library.

---

## 5. P0.5 — Vendor-Master Excel Inspection

**File:** `nationlabs-orchestrator\data_templates\vendor_master.xlsx` — **[VERIFIED]**

- Sheet `vendors`: **3 rows total (header + 2 demo vendors)**, 15 columns:
  `vendor_name, tier, tech_domains, product_family, contact_name, job_title, email, phone, country, vendor_authorised, deal_reg_capable, role, assigned_nl_owner, contact_status, last_validated`
- Companion `ownership_matrix.xlsx`: header + 2 demo rows, 8 columns (`tech_domain, oem, product_family, primary_owner, backup_owner, commercial_owner, technical_reviewer, escalation_manager`).

### 5.1 Findings & gaps

1. **Schema is fit-for-purpose** — the 15 columns cover what the workflow needs (tier for OEM/distributor disclosure logic, `deal_reg_capable` for the DR gate, `role` + `assigned_nl_owner` for routing). The prototype DB `vendors` table mirrors it 1:1 plus `email_domain`. ✅ schema, ❌ data.
2. **Gap G-2 [MISSING]: the real vendor master.** Production needs NationLabs' actual vendor/supplier contact list — all OEMs, distributors, resellers across IT infra, Network & Security, VOIP, AI/GPU, Subscriptions. **Action A-5.1 (owner: Raghu):** export the live Excel the team maintains today; deliver as `.xlsx`. Target: before Phase 1 vendor-master service build (P1-08).
3. **Data-quality rules to apply on import** (defined now so the real file can be scored on arrival):
   - `email_domain` extracted and validated; personal-domain contacts (gmail/outlook) flagged for manual review — RFQs carry end-user data, domain verification is a security control.
   - `vendor_authorised` / `deal_reg_capable` must be explicit yes/no — blank = treated as **no** (fail-closed).
   - `last_validated` older than 180 days → vendor flagged `contact_status=STALE`, warning on RFQ draft.
   - Duplicate detection on (vendor_name, email_domain).
4. **Ownership matrix is equally thin** (2 demo rows). The real technology→owner mapping drives alert routing and approval assignment. **Action A-5.2 (owner: Raghu + Niren):** confirm the real ownership matrix alongside the approval worksheet in §6.

---

## 6. P0.6 — Approval-Matrix Confirmation Worksheet

**Purpose:** close D3 (final approval thresholds) with Niren/Finance signatures before Phase 1 codes the configurable matrix. The orchestrator reads this from config — **no threshold is a constant in code** — but the shipping defaults must be signed here.

### Worksheet AM-1 (fill + sign)

| Rule | Condition (AED, total after VAT) | Approver role | SLA | Delegation when absent | Your confirmation |
|---|---|---|---|---|---|
| AM-R1 | < 60,000 | Assigned final verifier | ___ h | ___ | ☐ Confirmed / ☐ Change to: ___ |
| AM-R2 | 60,000 – 200,000 | ___ (TBC — presales manager? commercial owner?) | ___ h | ___ | ☐ Confirmed / ☐ Change to: ___ |
| AM-R3 | > 200,000 | Finance / Accounts team | ___ h | ___ | ☐ Confirmed / ☐ Change to: ___ |
| AM-R4 | End-user disclosure to OEM/distributor (any value) | Deal owner + ___ | before send | none (hard gate) | ☐ Confirmed / ☐ Change to: ___ |
| AM-R5 | Deal-registration waiver (send RFQ without DR) | ___ or **never allowed** | — | — | ☐ Never allowed / ☐ Waiver by: ___ |
| AM-R6 | Costing check failure override | ___ | — | — | ☐ No override / ☐ Override by: ___ |
| AM-R7 | Proposal release to customer | ___ | — | — | ☐ Confirmed / ☐ Change to: ___ |

**Sign-off:** Niren ________  Finance ________  Date ________

> Notes: AM-R2's 60K lower bound is the [TBC] tier from Architecture v2.0 §26. AM-R5 encodes the prototype's current behavior (RFQ blocked while DR pending — verified in demo). If NationLabs ever wants a waiver path, it must be a named role, never a silent skip.

---

## 7. P0.7 — Windows Office Automation Feasibility Test Plan

**Concept approved; implementation deferred (D1).** Phase 0 deliverable = the test plan that de-risks it. Already established: **pywin32 312 + Word/Excel 16.0 COM work on your desktop** [VERIFIED]; Track B golden-mirror CP succeeded through Word COM [VERIFIED]. What is NOT yet proven is *unattended, server-grade* operation.

### Test matrix WT (run on the candidate Windows document-worker VM)

| # | Test | Pass criteria | Risk it retires |
|---|---|---|---|
| WT-1 | Word COM headless open → find/replace → save → quit, 50 consecutive docs, no interactive session | 50/50 success, no ghost `WINWORD.EXE` | COM leaks / dialog hangs |
| WT-2 | Excel `Range.Copy` → Word `PasteSpecial` EMF paste at service account (no desktop login) | EMF renders identically to desktop run | Non-interactive clipboard failure (the classic COM-on-server trap) |
| WT-3 | PDF export fidelity | PDF page count + rasterized diff vs reference ≤ threshold | PDF-as-contract risk |
| WT-4 | Kill-switch watchdog: inject a modal dialog (protected-view prompt); watchdog must detect hang, kill process, quarantine doc, alert | Detection ≤ 60 s, clean recovery | The #1 documented failure mode of Office automation |
| WT-5 | Visual regression: LibreOffice render vs Word render of same docx | Perceptual diff ≤ agreed threshold | Cross-renderer drift hiding template breakage |
| WT-6 | Concurrent isolation: 2 jobs serialized through single worker queue | No interleaved COM state | COM is single-threaded apartment — queue discipline mandatory |
| WT-7 | Reboot survival: worker service auto-starts, queue resumes from PostgreSQL state | Zero lost jobs after reboot | Ops fragility |
| WT-8 | Malware boundary: worker receives files only from quarantine-cleared store (ClamAV pass) | No direct intake path exists | Document-worker as attack surface (D7 linkage) |

**Environment question for D1 decision:** Windows Server 2019 VM + Office LTSC (volume) vs Windows 11 VM + Microsoft 365 Apps. Server+LTSC recommended for licensing stability in unattended mode; Microsoft explicitly "unsupported but works" for server-side Office automation — hence watchdog + quarantine are non-negotiable. **Decision owner: Niren/IT procurement.**

---

## 8. P0.8 — Historical Evaluation-Dataset Collection Plan

**Purpose:** the benchmark gate (approved decision #13) that confirms or rejects qwen3:14b / gemma3:4b (D2). No dataset, no model sign-off — this is the single most important Phase 0/1 boundary artifact.

### 8.1 What to collect — 30–50 historical deals

| # | Artifact per deal | Why it's needed | Ground truth to label |
|---|---|---|---|
| 1 | Original RFP/RFC as received (WhatsApp text, email, PDF, scan) | Extraction + classification benchmark input | Customer/end-user org, contact, technology, brand, model, qty, deadlines; CP/TP/AMC label; new-vs-renewal; tech domain |
| 2 | The RFQ(s) actually sent (per vendor) | RFQ-drafting quality reference | Which vendors were chosen & why; was end-user disclosed |
| 3 | Vendor quote(s) received (native format — PDF/Excel/email) | Quote-extraction benchmark (the named hard problem) | Line items, unit/total prices, currency, VAT, validity, payment/delivery terms |
| 4 | Final costing sheet | Deterministic-calculator validation | Margins, totals — calculator must reproduce exactly |
| 5 | Final CP / TP / AMC as sent | Template + content fidelity reference | Proposal type produced; approval path actually taken; deal value band |
| 6 | Outcome (won/lost/abandoned + dates) | Timing stats for follow-up cadence tuning | — |

### 8.2 Collection mechanics

- **Mix target:** ≥8 deals per proposal type where possible (CP / TP / AMC), ≥5 tech domains, ≥10 distinct vendors, ≥20% multi-vendor-quote deals, ≥5 renewals. Include **at least 3 messy cases** (incomplete RFP, vendor quote with arithmetic error, mid-cycle revised quote) — benchmarks without failure cases prove nothing.
- **Anonymization:** real end-user names may stay (air-gapped, internal benchmark) **unless** the dataset will ever leave the building — decide once, record here: ☐ keep real / ☐ pseudonymize.
- **Format:** one folder per deal `deal-001/{rfp, rfq, quotes, costing, proposal, outcome}/` + `labels.xlsx` row. A collection script + label template is a Phase 1 backlog item (P1-14).
- **Owner:** Raghu collects; a presales colleague validates labels (second pair of eyes — labels are ground truth, errors poison the gate).
- **Timeline:** target 2 calendar weeks from kickoff; benchmark run is Phase 1 exit criterion E-1.
- **Pass thresholds (from Architecture v2.0 §19, restated):** extraction field-accuracy ≥95% on money/identity fields; classification (CP/TP/AMC + tech domain) ≥95%; quote line-item extraction ≥95% with 100% on totals-after-VAT; JSON validity ≥99% after one retry. Below threshold → model swap evaluation (qwen3:32b-class on the same A30, or task re-decomposition), **not** threshold relaxation.

---

## 9. P0.9 — Commercial Multi-Vendor & Quote-Version Data Model

**Requirement driving this section:** one opportunity solicits **many** vendors; each vendor may return **multiple quote revisions**; comparison must be apples-to-apples per line item; the accepted quote (and only it) feeds proposal pricing. Deferred AMC (D4) is accommodated at schema level.

### 9.1 Entity DDL (PostgreSQL 16 — excerpt, full DDL in Phase 1 migration)

```sql
-- one RFQ round per vendor per opportunity
CREATE TABLE rfqs (
  rfq_id          TEXT PRIMARY KEY,              -- NL-RFQ-2026-0007
  opp_id          TEXT NOT NULL REFERENCES opportunities(opp_id),
  vendor_id       INT  NOT NULL REFERENCES vendors(vendor_id),
  round_no        INT  NOT NULL DEFAULT 1,       -- re-solicitation rounds
  disclose_end_user BOOLEAN NOT NULL DEFAULT FALSE,
  disclosure_approved_by TEXT,                   -- NULL ⇒ not approved ⇒ blocked
  status          TEXT NOT NULL,                 -- DRAFT/APPROVED/SENT/CLOSED/EXPIRED
  idempotency_key TEXT NOT NULL UNIQUE,          -- duplicate-send prevention
  sent_at         TIMESTAMPTZ,
  response_deadline DATE,
  UNIQUE (opp_id, vendor_id, round_no)
);

-- every vendor reply, raw preserved, 1:N under an RFQ
CREATE TABLE vendor_responses (
  response_id     BIGSERIAL PRIMARY KEY,
  rfq_id          TEXT NOT NULL REFERENCES rfqs(rfq_id),
  raw_doc_path    TEXT NOT NULL,                 -- quarantine-cleared store path
  raw_sha256      TEXT NOT NULL,                 -- hash-chained audit anchor
  received_at     TIMESTAMPTZ NOT NULL,
  parse_status    TEXT NOT NULL DEFAULT 'PENDING'  -- PENDING/PARSED/FAILED_REVIEW
);

-- a parsed quote; revisions of the same vendor quote share quote_group_id
CREATE TABLE quotes (
  quote_id        BIGSERIAL PRIMARY KEY,
  quote_group_id  TEXT NOT NULL,                 -- e.g. QG-2026-0042 (vendor's own ref)
  opp_id          TEXT NOT NULL REFERENCES opportunities(opp_id),
  vendor_id       INT  NOT NULL REFERENCES vendors(vendor_id),
  response_id     BIGINT NOT NULL REFERENCES vendor_responses(response_id),
  version_no      INT  NOT NULL,                 -- 1,2,3… per quote_group_id
  is_current      BOOLEAN NOT NULL,              -- exactly one current per group
  currency        CHAR(3) NOT NULL,
  total_before_vat NUMERIC(14,2),
  vat_pct         NUMERIC(5,2),
  vat_amount      NUMERIC(14,2),
  total_after_vat NUMERIC(14,2),                 -- deterministic recompute, never LLM-trusted
  validity_date   DATE,
  extraction_confidence NUMERIC(4,3),
  status          TEXT NOT NULL,                 -- RECEIVED/VALIDATED/SHORTLISTED/ACCEPTED/REJECTED/SUPERSEDED
  UNIQUE (quote_group_id, version_no)
);
CREATE UNIQUE INDEX one_current_per_group ON quotes(quote_group_id) WHERE is_current;

-- line items: comparison and BOQ construction happen here, never on totals
CREATE TABLE quote_line_items (
  line_id         BIGSERIAL PRIMARY KEY,
  quote_id        BIGINT NOT NULL REFERENCES quotes(quote_id),
  line_no         INT  NOT NULL,
  sku             TEXT,
  description     TEXT NOT NULL,
  qty             NUMERIC(12,2) NOT NULL,
  unit_price      NUMERIC(14,2) NOT NULL,
  line_total      NUMERIC(14,2) NOT NULL,        -- recomputed: qty*unit_price, checked
  is_amc_line     BOOLEAN NOT NULL DEFAULT FALSE, -- D4 accommodation, workflow deferred
  match_key       TEXT                            -- normalized desc for cross-vendor matching
);

-- each comparison run is preserved (reproducibility for audits)
CREATE TABLE comparison_runs (
  run_id          BIGSERIAL PRIMARY KEY,
  opp_id          TEXT NOT NULL REFERENCES opportunities(opp_id),
  ran_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  input_quote_ids BIGINT[] NOT NULL,
  result_json     JSONB NOT NULL,                -- normalized comparison matrix
  chosen_quote_id BIGINT REFERENCES quotes(quote_id),
  chosen_by       TEXT,                          -- human chooser — AI recommends, human selects
  chosen_at       TIMESTAMPTZ
);
```

### 9.2 Rules the schema enforces

1. **Totals are recomputed deterministically** (`qty×unit`, `Σlines`, VAT) and compared to extracted values; mismatch → `costing_checks` failure row → human review. LLM output is a *claim*, the calculator is the *truth*. (Approved decision #9.)
2. **One current version per quote group** — partial unique index; supersession is an explicit transaction writing `SUPERSEDED` + new `is_current`.
3. **Rejection ≠ deletion** — rejected/superseded quotes, and rejected deals overall, are retained (Architecture v2.0 §5.9 End-User discrepancy rule).
4. **Idempotency key on every external-send row** — duplicate RFQ prevention is structural, not vigilance.
5. **AMC lines are representable today** (`is_amc_line`) so the deferred AMC workflow (D4) doesn't force a schema migration later.
6. Multi-currency: store native currency; AED normalization happens in `comparison_runs` with the rate + rate-date recorded in `result_json`.

---

## 10. P0.10 — Phase 1 Implementation Backlog with Acceptance Tests

**Scope discipline:** every item maps to an *approved* decision. Deferred items (D1–D8) appear only as preparatory tasks, never as shipped behavior. Estimates in person-days (pd). Each acceptance test is automatable and binary.

### P1-A · Foundations (infrastructure)

| ID | Item (decision ref) | Est. | Acceptance test |
|---|---|---|---|
| P1-01 | VM resize to 16 vCPU / 48–64 GB + re-run full inventory script; record actuals | 1 | Inventory report shows ≥16 vCPU, ≥48 GB; `nvidia-smi` clean; report committed to repo |
| P1-02 | PostgreSQL 16 + pgvector installed (air-gap `.deb` bundle), PITR backup job, append-only audit schema with hash chain | 3 | `pg_vector` ext loads; WAL archive → restore drill recovers to chosen timestamp; audit insert→tamper→verify detects tamper |
| P1-03 | Docker Compose MVP stack on AI VM: FastAPI app, Postgres, Ollama (existing), worker queues — single `docker compose up` | 3 | Cold boot → full stack healthy ≤ 3 min; `/healthz` green; reboot-survival test passes |
| P1-04 | Remove `deepseek-r1:32b`; set `MAX_LOADED_MODELS=2` policy for qwen3+gemma3 | 0.5 | `ollama list` shows exactly 2 models; disk freed ≥19 GB |
| P1-05 | Inventory `guardrails-prod/uat` containers: docs, API, fit vs v2.0 guardrail rails; decide reuse/replace | 2 | Written decision memo; if reused, contract test against its API passes |
| P1-06 | Repo + CI skeleton (offline): mono-repo, lint, pytest, migration runner | 2 | CI runs green on clean checkout without network |

### P1-B · Core orchestration (LangGraph + FastAPI monolith)

| ID | Item (decision ref) | Est. | Acceptance test |
|---|---|---|---|
| P1-07 | LangGraph state machine: intake → extract+classify (merged single call) → readiness gate → clarification loop; Postgres checkpointer | 5 | Scripted RFP walks to `CLARIFICATION_REQUIRED` or `READY`; kill -9 mid-graph → resumes from checkpoint with zero duplicate side-effects; token metrics row written per node |
| P1-08 | Vendor-master service: real Excel import (G-2 data), validation rules of §5.1, DB-backed matching | 3 | Import of real file produces validation report; stale/blank `deal_reg_capable` rows fail-closed; duplicate-domain detection fires on seeded dupe |
| P1-09 | Deal-registration gate + RFQ drafting with idempotent send queue; end-user disclosure only with approval (AM-R4) | 4 | DR-pending RFQ is BLOCKED (structural, not prompt); two clicks on "send" = one email (idempotency key); OEM gets end-user only after recorded approval; distributor path redacts |
| P1-10 | Follow-up scheduler: daily-morning cadence, stop-on-quote, escalation after N (config) | 2 | Simulated clock: follow-ups fire daily until quote lands; escalation at N; **ported prototype regression tests green (see P1-12)** |
| P1-11 | Approval engine reading signed matrix (Worksheet AM-1) from config | 2 | Changing threshold in config (no code change) reroutes 200,001 AED proposal to Finance; every approval persisted with actor+timestamp |
| P1-12 | Port prototype follow-up module; fix its 3 failing tests during port (do not carry the bug) | 2 | The 3 failing scenarios pass against the new service |
| P1-13 | Human-in-loop review UI: extraction corrections, quote acceptance, approval inbox | 5 | Reviewer correction re-scores readiness; all actions in audit log; no external send exists without a human click |

### P1-C · Quote intelligence + RAG

| ID | Item (decision ref) | Est. | Acceptance test |
|---|---|---|---|
| P1-14 | Historical-dataset collection pack: folder script + `labels.xlsx` template; **Raghu collects 30–50 deals (§8)** | 2 (+collection) | ≥30 deals with complete labels pass schema validation |
| P1-15 | Quote ingestion bridge: reuse Track A parsers (email/PDF/image/table) behind one service API; results into `quotes` + `quote_line_items` (§9) | 4 | Each historical quote in dataset parses; unparsable → `FAILED_REVIEW` queue, never silent drop |
| P1-16 | Deterministic quote validation: totals/VAT recompute, mismatch → costing-check failure | 2 | Seeded arithmetic-error quote is caught 100% of runs; corrected quote passes |
| P1-17 | pgvector RAG: 4 collections (approved content only), chunking rules (never split a pricing row), embedding model baked offline | 4 | Retrieval returns only approved-flagged chunks; pricing-row chunk integrity test; hallucination tripwire: proposal drafter receives *accepted quote* facts, RAG supplies language only |
| P1-18 | Multi-vendor comparison: normalized matrix, human selection, comparison_runs preserved | 3 | 3-vendor sample produces matrix; rerun with same inputs = byte-identical result_json |

### P1-D · Proposal generation + document worker

| ID | Item (decision ref) | Est. | Acceptance test |
|---|---|---|---|
| P1-19 | Proposal builder service wrapper around Track A (Node service as-is): CP path end-to-end from accepted quote | 3 | Generated CP passes immutable-part SHA-256 check (template-spec) and contains accepted-quote numbers exactly |
| P1-20 | TP golden-fidelity gate: Track A TP output vs `golden-tp.docx` visual regression (closes G-1) | 3 | Rasterized diff within threshold; 16-inline-shape structure preserved; narrative sections populated from RAG + accepted quote |
| P1-21 | Windows document-worker MVP: queue consumer, Word render + PDF export, watchdog + quarantine (concept approved; WT-1…WT-8 executed) | 5 | WT-1, WT-2, WT-4, WT-7 pass on candidate VM; failures documented for D1 decision |
| P1-22 | Proposal release flow per AM-R7 + sign-off routing; PDF-as-contract archived with hash | 2 | Released proposal package (docx+pdf+hash) lands in document store; audit trail complete from RFP to release |

### P1-E · Benchmarks & go/no-go

| ID | Item (decision ref) | Est. | Acceptance test |
|---|---|---|---|
| P1-23 | Benchmark harness: replay §8 dataset through extraction/classification/quote parsing; score vs thresholds | 3 | Report auto-generated: per-field accuracy, confusion matrix, latency, token cost |
| P1-24 | **Model go/no-go (D2):** qwen3:14b + gemma3:4b vs §8.2 thresholds | 1 | Decision memo signed: pass → models confirmed; fail → documented swap evaluation (never silent threshold relaxation) |
| P1-25 | Security pass: ClamAV intake pipeline, injection-defense prompts on hostile quote samples, AD/LDAP auth wiring | 4 | EICAR-file blocked at intake; 3 crafted injection quotes neutralized; login via AD group; D7 sufficiency notes written for review |

**Phase 1 totals:** ≈ 70 person-days core + collection effort. **Exit criteria:** E-1 benchmark gate passed (P1-24); E-2 one full lifecycle (intake→CP) executed on production-like stack with zero manual code touches; E-3 all acceptance tests above green in CI.

### 10.1 Gap & action register (consolidated)

| ID | Gap / action | Owner | Needed by |
|---|---|---|---|
| G-1 | Golden-fidelity TP unproven | Kimi build | P1-20 |
| G-2 | Real vendor-master Excel | Raghu | P1-08 |
| A-4.1 | Golden AMC confirmation or supply | Niren | Before AMC workflow (post-D4) |
| A-5.2 | Real ownership matrix | Raghu + Niren | P1-11 |
| AM-1 | Approval worksheet sign-off | Niren + Finance | P1-11 |
| §8 | 30–50 historical deals + labels | Raghu + validator | P1-14 → P1-23 |
| D1-input | Windows/Office licensing decision | Niren/IT | P1-21 environment |
| R-1 | DB/inference co-location (D6) — interim accepted, target topology open | Niren | Pre-production |
| R-3 | VM undersized vs v2.0 | Raghu/IT | P1-01 |

---

## 11. Phase 0 Verdict

1. **The estate is stronger than assumed.** The discovery that `C:\NL\proposal-builder` already contains a tested, deterministic CP/TP/AMC generator with SHA-256-pinned immutable template parts and a vendor-quote parsing suite materially de-risks the two hardest mandates: Niren's zero-deviation format and quote ingestion.
2. **The prototype did its job** — workflow, prompts, gates, audit are proven — and must now be *ported, not patched* (3 failing follow-up tests confirm demo-grade).
3. **The binding constraints are inputs, not engineering:** real vendor master, real ownership matrix, signed approval worksheet, golden AMC confirmation, and the 30–50-deal benchmark dataset. Four of those five sit with Raghu/Niren, not with the build.
4. **One hardware action** (VM resize) removes the only resource red flag.

**Phase 0 status: COMPLETE — pending the five owner-supplied inputs above.**

*End of Phase 0 Discovery & Gap Assessment v1.0*
