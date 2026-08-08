# NationLabs AI Presales Orchestrator — Solution Architecture v2.0

**Status:** v2.0 — Production-oriented architecture & implementation blueprint (no code)
**Supersedes:** v1.0 (2026-08-05) — business understanding preserved, platform architecture corrected
**Author:** Principal Solution Architect & Product Engineering Lead (Kimi)
**Date:** 2026-08-05 · **Audience:** Raghu (build owner), Niren (proposal quality gatekeeper), NationLabs IT, TAL Group reviewers

> **Reading guide.** Sections 1–9 set context and target shape. Sections 10–19 are the engineering core (workflow, modules, orchestration, data, RAG, AI, document path). Sections 20–27 cover platform concerns (APIs, security, observability, DR, benchmarks, sizing). Sections 28–34 cover delivery, decisions, acceptance and honest critique. Every unconfirmed business value is marked **[TBC — business confirmation required]**.

---

## 1. Executive Summary

NationLabs receives RFPs through unstructured channels (WhatsApp, word of mouth) and responds with rigidly formatted Commercial, Technical and AMC proposals. Today this is manual, slow, and depends on individual diligence for deal registration, costing correctness and format compliance.

This architecture defines a **business-critical, air-gapped presales workflow and proposal orchestration platform** that:

- runs entirely inside NationLabs' isolated network on the existing Dell R750 (A30 24 GB GPU) estate;
- uses local LLMs (via Ollama) to **read, extract, classify, recommend and draft** — but never to decide arithmetic, never to send anything externally, and never to bypass a human gate;
- treats **deal registration as a hard workflow gate**, quote arithmetic as **deterministic application logic**, and the golden proposal templates as an **inviolable format of record**;
- orchestrates weeks-long, human-in-the-loop workflows with **LangGraph**, with **PostgreSQL as the sole authoritative state store**;
- grounds all proposal wording in a **local RAG knowledge base of approved content only**, with citations and provenance;
- generates final DOCX/PDF through the **existing proposal builder**, exposed as an internal service, executed on an isolated, hardened **Windows document worker** with automated structural and visual validation;
- records **every** action, transition, approval, override, retrieval and build in an append-only, hash-chained audit log.

v2.0 corrects v1.0 in five mandated areas: PostgreSQL replaces SQLite; a durable LangGraph orchestration layer with persisted checkpoints replaces ad-hoc state handling; a full RAG/knowledge architecture is specified; the approval engine becomes a configurable matrix (not a hard-coded 200K rule); and security expands from "the human is the DMZ" to a complete trust-zone, identity, file-security and AI-security design.

## 2. Business Context

| Verified fact | Detail |
|---|---|
| Compute | Dell PowerEdge R750, 48 logical cores, 128 GB RAM, NVIDIA A30 24 GB (ECC, TCC mode); chassis accepts a second double-width GPU |
| AI VM | **Ubuntu** VM, Ollama; models `qwen3:14b` (main), `gemma3:4b` (fast rails); both **subject to benchmarking (§26)** before production confirmation |
| Network | Fully air-gapped; no internet egress for any platform component |
| Intake reality | RFPs arrive as WhatsApp messages, phone notes, word of mouth; later PDF/DOCX/XLSX; scanned images in a controlled later phase |
| Deal shapes | New requirement / renewal; domains: IT infra, network & security, VOIP, AI/GPU, subscriptions |
| Proposal types | CP, TP, AMC — golden Word templates are the format of record; zero deviation tolerated (Niren) |
| Golden format specifics | BOQ and costing sheets embedded as **Excel metafile (EMF) pastes**; Century Gothic; per-vendor validity/delivery bullets; fixed letter and acceptance blocks |
| Hard business rules | Deal registration mandatory and gating; humans approve and send every external communication; approval thresholds configurable (200K AED→Finance is one rule, not the rule) |
| Master data | Vendor/distributor contacts in an Excel sheet (requires one-time cleanse) |
| Existing assets | Working Kimi-built prototype (intake→analysis→RFQ→deal-reg→quote→validation→routing, 17/17 tests); proven Word/Excel COM golden-exact build on desktop; existing NationLabs proposal builder to be **reused as a service** |

## 3. Confirmed Requirements (preserved from v1.0 review)

1. Fully air-gapped operation; no external cloud AI APIs.
2. Existing Ubuntu VM + A30 + Ollama utilised; local models retained subject to §26 benchmarks.
3. Intake: manual paste (WhatsApp/verbal), PDF, DOCX, XLSX; scanned images in a later controlled phase.
4. AI may analyse, extract, classify, recommend, draft. AI must never autonomously send RFQs, emails, proposals or any external communication.
5. Mandatory human approval before every external communication; final customer submission under human control.
6. Deal registration = hard workflow gate.
7. All quote/costing/VAT/margin arithmetic = deterministic application logic, never LLM output.
8. CP/TP/AMC golden templates are the format of record; the **existing proposal builder is reused**, exposed as an internal document-generation service; a dedicated Windows document worker is used where genuine Word/Excel is required.
9. Full auditability of every action, transition, approval, override, retrieval and generated document.
10. The system supports pause, resume, retry, rejection, rework and manual override.

## 4. Open Business Decisions

| # | Decision | Why it matters | Owner |
|---|---|---|---|
| D1 | Approval matrix: thresholds & approvers (incl. the AED 60,000 intermediate tier, CEO tier, >200K Finance+TAL tier) | Drives approval engine config | Niren / Finance / TAL **[TBC]** |
| D2 | Windows document-worker VM + **licensed MS Office** | Only new procurement; blocks golden-exact generation in production | NationLabs IT |
| D3 | AMC golden template sample + confirmation AMC follows the same format family | AMC builder cannot start without it | Niren **[TBC]** |
| D4 | AD/LDAP availability inside the air gap | Chooses enterprise auth vs local accounts | NationLabs IT **[TBC]** |
| D5 | Approved content library: who authors/approves per-technology TP bodies and standard clauses | RAG content quality gate | Niren + presales leads |
| D6 | Internal SMTP relay availability (for optional internal notifications only) | Follow-up reminders channel | NationLabs IT **[TBC]** |
| D7 | Data retention & customer-specific retention policies | Compliance + storage sizing | Niren / legal **[TBC]** |
| D8 | Secure-entity handling rules (which customers are "secure entities", what extra restrictions apply) | Drives customer-level access controls | Niren **[TBC]** |

## 5. Design Principles

1. **Deterministic at the money edges.** Extraction and drafting may be probabilistic; costing, VAT, margin, totals, thresholds and routing are code.
2. **Humans hold the keys.** Three explicit human gates minimum: approve external drafts, confirm deal registration, sign off proposals. No autonomous sends exist in the codebase.
3. **One source of truth.** PostgreSQL is authoritative for all business state; LangGraph checkpoints are recoverable execution state, not business truth.
4. **Approved content only reaches customers.** RAG retrieval is restricted by approval status; the proposal builder receives only validated structured payloads.
5. **Format of record is untouchable.** Golden templates are hash-registered and version-locked; documents are produced only by the approved document-generation service.
6. **Everything is auditable, everything is recoverable.** Hash-chained audit; every workflow resumable after restart; every build idempotent.
7. **Boring technology where possible, precision engineering where required.** PostgreSQL, FastAPI, Prometheus — proven; the two genuinely novel parts (LLM extraction quality, COM document fidelity) get dedicated hardening and evaluation.
8. **Degrade gracefully.** If the GPU or models are down, the platform still runs in manual mode; if the document worker is down, deals still progress to the build queue.

## 6. Target Architecture

Modular services behind an API layer — **not one large AI agent**. Services share the PostgreSQL system of record, call models only through the Model Gateway, and call the document path only through the Proposal Builder Integration Service.

Layers:
- **Experience:** server-rendered web UI + REST API (OpenAPI).
- **Orchestration:** LangGraph workflow graphs (durable, checkpointed, human-in-the-loop).
- **Domain services (28 modules, §13):** intake → extraction → classification → readiness → masters → matching → RFQ → deal-reg → communications → RFI → response classification → quote → validation → costing/margin → solution drafting → proposal data assembly → approvals → builder integration → follow-ups → audit → knowledge/RAG → model gateway → evaluation → admin → reporting.
- **Platform:** PostgreSQL (+pgvector), Model Gateway (Ollama), object/file store, observability stack.
- **Document path:** Proposal Builder Integration Service → Windows Document Worker (existing proposal builder + Word/Excel COM) → automated validation → human preview.

## 7. Logical Architecture Diagram

```
                ┌────────────────────────────────────────────────────────────┐
                │                    User Workstations (browser)              │
                └───────────────────────────┬────────────────────────────────┘
                                            │ TLS (LAN)
                ┌───────────────────────────▼────────────────────────────────┐
                │        API & Web Layer (FastAPI, OpenAPI, server-rendered) │
                ├───────────────────────────┬────────────────────────────────┤
                │   Workflow Orchestration  │         Domain Services        │
                │   (LangGraph graphs;      │  (28 modules, §13; deterministic│
                │    human-in-the-loop)     │   logic + AI-assisted nodes)   │
                ├───────────────────────────┼────────────────────────────────┤
                │  Model Gateway  │  Knowledge & RAG  │  Audit & Compliance  │
                │  (Ollama:       │  (pgvector;       │  (hash-chained,      │
                │   qwen/gemma)   │   approved-only)  │   append-only)       │
                ├─────────────────┴───────────────────┴──────────────────────┤
                │        PostgreSQL — authoritative system of record         │
                │  (business data + workflow state + checkpoints + vectors)  │
                ├────────────────────────────────────────────────────────────┤
                │   Immutable File Store (originals + generated documents)   │
                └───────────────────────────┬────────────────────────────────┘
                                            │ internal REST (build jobs)
                ┌───────────────────────────▼────────────────────────────────┐
                │   Windows Document Worker VM (isolated zone)               │
                │   Existing Proposal Builder + Word/Excel COM               │
                │   serial queue · watchdog · validation · quarantine        │
                └────────────────────────────────────────────────────────────┘
```

## 8. Physical Deployment Diagram

```
Dell R750 hypervisor (NLABDLAS01, air-gapped)
├── VM-1  Ubuntu AI VM              [zone: ai-app]      24 vCPU · 72 GB · 1.5 TB · A30 passthrough
│         ├── Docker: orchestrator app (FastAPI), LangGraph workers
│         ├── Docker: PostgreSQL 16 + pgvector        (primary DB)
│         ├── Docker: Ollama (qwen3:14b, gemma3:4b)   (GPU)
│         ├── Docker: Prometheus, Grafana, Loki, node exporter, GPU exporter
│         └── File store volume (originals, proposals, backups staging)
├── VM-2  Windows Document Worker   [zone: doc-worker]   4 vCPU · 16 GB · 250 GB
│         Windows Server 2022 · MS Office (licensed) · Doc-Build service · watchdog
├── VM-3  (Phase 3+) DB standby     [zone: data]         4 vCPU · 16 GB — PostgreSQL streaming replica
├── NAS / backup target             [zone: backup]      encrypted, offline rotation copy
└── Workstations / admin laptops    [zone: user / admin]
Hypervisor virtual switches enforce zone segmentation; no VM has an internet gateway.
```

## 9. Trust-Zone and Security Diagram

```
        ┌──────────────────────── AIR-GAPPED TRUST BOUNDARY ────────────────────────┐
        │                                                                           │
        │  user zone          ai-app zone              doc-worker zone   admin zone │
        │  ┌────────┐   TLS   ┌──────────────┐   TLS   ┌──────────────┐  ┌────────┐ │
        │  │browser │◄───────►│ orchestrator │◄───────►│ doc build    │  │ops jump│ │
        │  └────────┘         │  + API       │  allow- │  service     │  └───┬────┘ │
        │                     │  + LangGraph │  listed │  (Win+Office)│      │      │
        │                     └──────┬───────┘         └──────────────┘      │      │
        │                            │ localhost-only                        │      │
        │                     ┌──────▼───────┐  ┌──────────────┐             │      │
        │                     │ PostgreSQL   │  │ Ollama (GPU) │             │      │
        │                     │ +pgvector    │  └──────────────┘             │      │
        │                     └──────┬───────┘                                │      │
        │        backup zone         │ encrypted                              │      │
        │  ┌──────────────┐◄─────────┘                                        │      │
        │  │ NAS + offline │                                                  │      │
        │  └──────────────┘                                                   │      │
        │  controlled-update zone: removable media station w/ checksum verify │      │
        └─────────────────────────────────────────────────────────────────────┘
 No default route to internet on any zone. Internal DNS/NTP/CA only. Firewall: default-deny,
 allow-list per flow (documented in §21).
```

---

## 10. End-to-End Workflow

The 47-step business workflow from the review brief, consolidated into operational stages (mapping to steps in parentheses):

**A. Intake & preservation (1–5):** create opportunity → enter customer/end-user → paste/upload requirement → immutable original stored (content hash) → file security pipeline (§21.3) runs.
**B. Understanding (6–12):** AI extraction (structured requirements) → user verifies fields → classification (opportunity type, proposal type, tech domain) → readiness score → missing info → RFI/clarification list → user obtains answers manually → clarifications recorded.
**C. Vendor engagement (13–24):** vendor/distributor matching → user validates selection → RFQ + deal-reg drafts (RAG-approved wording) → **human approves** → human sends from own client → sent status recorded → response tracking → replies pasted → reply classification (quote / RFI / deal-reg approval / rejection / condition / pricing / technical / other) → vendor RFIs become customer clarifications → follow-up reminders → deal-reg status tracked.
**D. Commercials (25–31):** quote extraction → deterministic arithmetic validation → duplicate/revision detection → validity/expiry tracking → cost components (freight, implementation, PM, support…) → margin calculation → margin policy check.
**E. Proposal assembly (32–37):** technical + commercial content assembled → RAG retrieval with citations (approved content only) → human validates design & pricing → dynamic approval routing → approvals/rejections/rework → approved structured payload to proposal builder.
**F. Document generation & QA (38–41):** Windows worker generates DOCX + PDF → automated structural validation (§19.4) → human preview → corrections return to the correct stage.
**G. Submission & closure (42–47):** final approval for submission → human sends to customer → submission evidence recorded → follow-ups continue → outcome recorded (won/lost/cancelled/expired/on hold) → retention per policy.

## 11. Workflow State Machine

### 11.1 States

| State | Meaning | Entry guard |
|---|---|---|
| `INTAKE` | Created, original preserved | — |
| `SECURITY_SCAN` | File checks running | files clean or quarantined |
| `UNDER_ANALYSIS` | AI extraction/classification running | scan passed |
| `CLARIFICATION_REQUIRED` | Readiness < threshold / fields missing | — |
| `READY_FOR_RFQ` | Extraction verified by user | user verification complete |
| `RFQ_DRAFTED` | Drafts generated | vendors validated by user |
| `AWAITING_RFQ_APPROVAL` | Human gate 1 open | — |
| `RFQ_SENT` | User confirmed send from own client | human key 1 |
| `AWAITING_VENDOR_RESPONSE` | Listening; follow-up loop active | — |
| `VENDOR_RFI_OPEN` | Vendor asked something; customer clarification pending | reply class = RFI |
| `QUOTE_RECEIVED` | ≥1 quote parsed | reply class = quote |
| `QUOTE_UNDER_VALIDATION` | Deterministic math check running | — |
| `QUOTE_VALIDATED` | Math + margin policy pass | deterministic checks green |
| `DEAL_REG_BLOCKED` | Deal-reg not Approved (sub-state visible at all times) | gate evaluation |
| `READY_FOR_PROPOSAL` | Content assembly permitted | quote validated AND deal_reg.status=Approved |
| `PROPOSAL_ASSEMBLY` | RAG-grounded drafting + data assembly | — |
| `IN_APPROVAL` | Dynamic approval chain executing | payload frozen (content hash) |
| `APPROVAL_REJECTED` | Returned with mandatory reason | rework → `PROPOSAL_ASSEMBLY` |
| `READY_FOR_BUILD` | All approvals granted | chain complete |
| `BUILDING` | Doc worker job running | idempotent build enqueued |
| `BUILD_QUARANTINED` | Build/validation failed | manual triage |
| `PENDING_HUMAN_PREVIEW` | DOCX+PDF validated, awaiting eyes | automated validation green |
| `READY_FOR_SUBMISSION` | Human preview approved | final sign-off recorded |
| `SUBMITTED` | User recorded customer submission + evidence | submission date + evidence |
| `FOLLOW_UP` | Post-submission chase | — |
| `CLOSED_WON / CLOSED_LOST / CANCELLED / EXPIRED / ON_HOLD` | Terminal-ish states | outcome + reason |

### 11.2 Key transitions (transition table excerpt — full table maintained in repo)

| From | Event | To | Actor | Guard |
|---|---|---|---|---|
| INTAKE | scan clean | UNDER_ANALYSIS | system | AV/hash checks pass |
| UNDER_ANALYSIS | readiness < threshold | CLARIFICATION_REQUIRED | system | score rubric |
| CLARIFICATION_REQUIRED | clarification recorded | UNDER_ANALYSIS | user | re-run extraction delta |
| READY_FOR_RFQ | drafts done | RFQ_DRAFTED | AI | ≥1 validated vendor |
| RFQ_DRAFTED | submit for approval | AWAITING_RFQ_APPROVAL | user | — |
| AWAITING_RFQ_APPROVAL | **approve** | RFQ_SENT-pending-confirm | **human** | approver ≠ drafter (maker-checker) |
| … | user confirms sent | RFQ_SENT | human | sent-date recorded |
| AWAITING_VENDOR_RESPONSE | reply pasted, class=quote | QUOTE_RECEIVED | user+AI | — |
| QUOTE_RECEIVED | math check pass | QUOTE_VALIDATED | system | deterministic |
| QUOTE_VALIDATED | deal-reg ≠ Approved | DEAL_REG_BLOCKED | system | gate |
| QUOTE_VALIDATED | deal-reg = Approved | READY_FOR_PROPOSAL | system | gate |
| READY_FOR_PROPOSAL | assemble complete | IN_APPROVAL | system | approval matrix evaluation |
| IN_APPROVAL | all steps approved | READY_FOR_BUILD | humans | chain complete, payload hash frozen |
| IN_APPROVAL | any reject | APPROVAL_REJECTED | human | reason mandatory |
| READY_FOR_BUILD | build success + validation green | PENDING_HUMAN_PREVIEW | system | §19.4 checks |
| PENDING_HUMAN_PREVIEW | preview approved | READY_FOR_SUBMISSION | human | — |
| READY_FOR_SUBMISSION | submission recorded | SUBMITTED | human | evidence attached |
| (any) | pause / hold | ON_HOLD | user | reason; resume returns to prior state |
| (any) | manual override | (target state) | admin | elevated role + reason + audit |

## 12. Human Approval Model

- **Three mandatory gates** (cannot be disabled): external-draft approval (maker-checker), deal-registration confirmation, proposal sign-off.
- **Configurable approval matrix** (PostgreSQL `approval_rule` + `approval_step` tables): rules evaluated on value, margin %, customer, secure-entity flag, proposal type; producing ordered chains with sequential/parallel steps, delegation, SLA, escalation, expiry.
- Sample matrix (**all thresholds [TBC]**):

| Condition | Chain (sequential) |
|---|---|
| value < 60,000 AED **[TBC]** | Assigned manager (Niren or delegate) |
| 60,000 ≤ value < 200,000 **[TBC]** | Manager → CEO or authorised approver |
| value ≥ 200,000 AED | Manager → Finance → TAL Group |
| margin < policy floor **[TBC %]** | + Finance exception step (any value) |
| secure-entity customer | + Legal/security review (any value) |

- Every approval step records: approver identity, decision, comments, evidence, timestamp, SLA state, delegation chain. Rejection forces rework to a defined stage with reason; re-approval starts from the rejected step only, not the whole chain.

---

## 13. Service and Module Design

All modules are services within one deployable application (modular monolith) for MVP/pilot, behind a service interface that allows later extraction into separate processes without API change. Each module entry: purpose · inputs → outputs · deterministic vs AI logic · human gates · tables · APIs · failure handling · audit events · dependencies.

### 13.1 Opportunity Intake Service
- **Purpose:** create opportunities; accept paste/upload; preserve immutable originals.
- **In:** pasted text, PDF/DOCX/XLSX, customer fields → **Out:** opportunity id, file refs.
- **Det:** file-type/size enforcement, content hashing, dedup. **AI:** none. **Human:** creation.
- **Tables:** opportunity, uploaded_file, customer, end_user, contact. **APIs:** `POST /opportunities`, `POST /opportunities/{id}/files`.
- **Failure:** oversize/invalid → reject with reason; storage error → retry, no partial records.
- **Audit:** `opportunity_created`, `file_uploaded(hash)`. **Deps:** File Security (§21.3), Customer Master.

### 13.2 Requirement Extraction Service
- **Purpose:** turn raw requirement text into structured fields/items.
- **In:** original text/file text → **Out:** extracted_field rows w/ Confirmed|Missing + confidence.
- **AI:** qwen-class model, JSON-schema-constrained, payload quarantined in delimiters. **Det:** schema validation, normalisation, retry.
- **Human:** field verification gate before RFQ. **Tables:** requirement, requirement_item, extracted_field, model_run.
- **APIs:** `POST /opportunities/{id}/extract`. **Failure:** malformed JSON → strict retry → human fallback w/ raw payload.
- **Audit:** `extraction_complete(model, prompt_version, confidence)`. **Deps:** Model Gateway, RAG (none at this stage).

### 13.3 Opportunity Classification Service
- **Purpose:** classify opportunity type (new/renewal), proposal type (CP/TP/AMC), tech domain.
- **AI:** 14b classification w/ per-label confidence; 4b rail for trivial cases. **Det:** confidence thresholds → human decision queue below floor.
- **Tables:** classification_result, model_run. **APIs:** `POST /opportunities/{id}/classify`.
- **Human:** override allowed, recorded. **Failure:** below threshold → `needs_human_decision`.
- **Audit:** `classification_complete(labels, confidences, overridden?)`.

### 13.4 Readiness & Missing-Information Service
- **Purpose:** deterministic completeness rubric → readiness score, missing-info list, RFI text.
- **Det only:** weighted rubric per proposal/domain type. **Tables:** readiness_score, clarification.
- **APIs:** `POST /opportunities/{id}/readiness`. **Failure:** n/a (pure code). **Audit:** `readiness_computed(score, missing[])`.

### 13.5 Customer & End-User Master Service
- **Purpose:** deduplicated customer/end-user registry; secure-entity flags; customer-level access.
- **Det:** fuzzy dedup suggestions; merge with audit. **Tables:** customer, end_user, contact. **APIs:** CRUD `/customers`.
- **Human:** merge confirmation. **Audit:** create/update/merge with actor. **Deps:** RBAC.

### 13.6 Vendor & Distributor Master Service
- **Purpose:** vendor/distributor contacts & capabilities; versioned master (imported from cleansed Excel).
- **Tables:** vendor, distributor, vendor_contact, vendor_capability, master_version. **APIs:** CRUD `/vendors`.
- **Human:** master edits restricted to admin role. **Audit:** every master change w/ version bump.

### 13.7 Vendor Matching Service
- **Purpose:** recommend vendors/distributors for a requirement set.
- **Det:** rule-first (domain + brand + capability + past performance). **AI:** tie-break ranking w/ rationale; never invents vendors.
- **Human:** user validates selection before drafting. **Tables:** vendor_match_result. **APIs:** `POST /opportunities/{id}/match_vendors`.
- **Audit:** `vendors_recommended(list, rationale_ref)`.

### 13.8 RFQ Drafting Service
- **Purpose:** generate RFQ emails incl. deal-registration request; end-user details **only** for OEM/Distributor recipient class (code-enforced).
- **AI:** draft body grounded in RAG-approved wording + extracted requirement. **Det:** template merge, recipient-class data filter, versioned drafts.
- **Human:** approval gate (human key 1); maker-checker. **Tables:** rfq, rfq_recipient, rfq_version. **APIs:** `POST /rfqs/draft`, `POST /rfqs/{id}/approve`, `POST /rfqs/{id}/confirm_sent`.
- **Failure:** recipient data incomplete → block with missing list. **Audit:** draft/approve/confirm w/ actor.

### 13.9 Deal Registration Service
- **Purpose:** track registration lifecycle: Submitted → Approved/Rejected/Conditional/Expired; hard gate evaluation.
- **Det:** gate rule, expiry scanning. **AI:** recognise deal-reg decisions in pasted replies (classification assist). **Human:** override w/ non-blank reason (elevated role).
- **Tables:** deal_registration. **APIs:** `GET/POST /opportunities/{id}/deal-registration`.
- **Failure:** expiry before quote → alert + renewal draft. **Audit:** status changes w/ evidence ref.

### 13.10 Vendor Communication Tracking Service
- **Purpose:** register every outbound (human-sent) and inbound (pasted) communication per RFQ/vendor.
- **Tables:** communication_thread, vendor_response. **APIs:** `POST /rfqs/{id}/responses`.
- **Det:** threading by RFQ + vendor; stale tracking. **Audit:** all records immutable.

### 13.11 RFI & Clarification Service
- **Purpose:** manage clarification lists to customer and RFIs from vendors; convert vendor RFI → customer clarification.
- **Tables:** clarification, rfi. **APIs:** `POST /opportunities/{id}/clarifications`.
- **Human:** all external wording approved. **Audit:** lifecycle w/ timestamps.

### 13.12 Vendor Response Classification Service
- **Purpose:** classify pasted replies: quote / RFI / deal-reg approval / rejection / condition / pricing / technical / other.
- **AI:** 14b w/ confidence; 4b rail for obvious classes. **Det:** low confidence → human class prompt.
- **Tables:** vendor_response, model_run. **APIs:** `POST /responses/{id}/classify`. **Failure:** misclassification → manual re-classify + feeds eval backlog (§26).
- **Audit:** `response_classified(class, confidence, overridden?)`.

### 13.13 Quote Extraction Service
- **Purpose:** structured line items, quantities, prices, validity, refs from quote text/files.
- **AI:** extraction to schema. **Det:** numeric coercion, currency normalisation, revision detection (same vendor+ref, new version).
- **Tables:** quote, quote_version, quote_line_item. **APIs:** `POST /quotes/extract`.
- **Failure:** no line items → human review. **Audit:** extraction w/ model+prompt versions.

### 13.14 Quote Validation Service
- **Purpose:** deterministic arithmetic: qty×unit=line; Σ=subtotal; subtotal+VAT=total; cross-check stated vs computed totals.
- **Det only.** **Tables:** quote_validation_result. **APIs:** `POST /quotes/{id}/validate`.
- **Failure:** mismatch → discrepancy list to human; never auto-"fix" vendor numbers. **Audit:** computed vs stated values.

### 13.15 Costing & Margin Service
- **Purpose:** add freight/implementation/PM/support/other components; compute sell price & margin; enforce margin policy.
- **Det only.** **Tables:** cost_component, margin_calculation, margin_policy. **APIs:** `POST /quotes/{id}/costing`.
- **Human:** finance-visible fields role-restricted. **Audit:** every component change w/ actor.

### 13.16 Technical Solution Drafting Service
- **Purpose:** draft TP body sections grounded in RAG-approved content w/ citations; new technologies → draft flagged for mandatory human review.
- **AI:** section drafting constrained by retrieved approved chunks. **Det:** citation attachment, approval-status filter.
- **Tables:** technical_solution, solution_section, citation. **APIs:** `POST /opportunities/{id}/solution/draft`.
- **Human:** technical review gate. **Audit:** retrieval events + draft provenance.

### 13.17 Commercial Proposal Data Assembly Service
- **Purpose:** assemble the validated CP payload (parties, refs, BOQ lines, terms per vendor, totals) for the builder.
- **Det only:** payload schema + completeness validation. **Tables:** proposal_payload. **APIs:** `POST /proposals/cp/assemble`.

### 13.18 AMC Proposal Data Assembly Service
- **Purpose:** same for AMC (coverage period, SLAs, assets). **[TBC: AMC golden template]** — API parity with 13.17.

### 13.19 Approval Routing Service
- **Purpose:** evaluate approval matrix → instantiate chains; execute sequential/parallel steps, delegation, SLA, escalation, expiry, rejection/rework.
- **Det only.** **Tables:** approval_rule, approval_request, approval_step, approval_decision. **APIs:** `POST /opportunities/{id}/route`, `POST /approvals/{id}/decision`.
- **Failure:** no matching rule → safe default chain + admin alert. **Audit:** full chain trace.

### 13.20 Proposal Builder Integration Service
- **Purpose:** single doorway to the document path: validate payload, freeze content hash, enqueue idempotent build, retrieve artifacts, register validation results.
- **Det only.** **Tables:** proposal, proposal_version, document_build_job, document_validation_result.
- **APIs:** `POST /proposals/{id}/build`, `GET /proposals/{id}/artifacts`. **Failure:** build error → quarantine, state never advances silently.

### 13.21 Windows Document Rendering Service (remote, §19)
- Executes the existing proposal builder under hardened COM control; returns DOCX+PDF+validation report.

### 13.22 Follow-up & Reminder Service
- **Purpose:** daily scan: stale vendor responses, quote expiry, deal-reg expiry, approval SLA breaches, post-submission chase → tasks + optional internal notifications **[TBC: SMTP]**.
- **Det only.** **Tables:** task, reminder. **APIs:** `GET /tasks`. **Audit:** reminder generation.

### 13.23 Audit & Compliance Service (§22)
- Append-only hash-chained event log; verification job; export for review.

### 13.24 Knowledge & RAG Service (§16)
- Ingestion, approval workflow, hybrid retrieval with provenance and access filters.

### 13.25 Model Gateway Service (§17)
- Single entry for all model calls: queueing, timeouts, retries, logging, version pinning.

### 13.26 Evaluation & Regression Testing Service (§26)
- Dataset management, benchmark runs, threshold gating, regression reports.

### 13.27 Administration & Configuration Service
- Users/roles, approval matrix editor (admin+audit), template registry, margin policy, feature flags.

### 13.28 Reporting & Dashboard Service
- Pipeline board, aging analysis, approval SLA, vendor responsiveness, model-latency panels; read-only.

---

## 14. LangGraph Orchestration Design

### 14.1 What belongs where
- **PostgreSQL (authoritative):** all business entities and their states (opportunity status, deal-reg status, approvals, quotes, proposals). A workflow's *position* is always derivable from business state.
- **LangGraph:** execution choreography — node sequencing, conditional edges, retries, human-in-the-loop interrupts, trace of node executions. Graphs are **stateless workers over DB state**; nodes read/write via domain services, never via private in-memory state.
- **LangGraph checkpoints:** persisted to PostgreSQL (official Postgres checkpointer), storing graph execution context (node cursor, scratch inputs) so a paused/crashed run resumes exactly.

### 14.2 Graph topology (opportunity lifecycle graph)
```
intake_node → security_scan_node → extraction_node → classify_node → readiness_node
   → [conditional] score<τ → clarification_node (HUMAN interrupt) → back to extraction delta
   → vendor_match_node → rfq_draft_node → rfq_approval_interrupt (HUMAN)
   → sent_confirm_node (HUMAN) → await_response_node (event-waiting)
   → response_classify_node → [conditional edges]
        quote → quote_extract_node → quote_validate_node → dealreg_gate_node
             → [gate fail] deal_reg_blocked_node (event-waiting on deal-reg approval)
             → [gate pass] proposal_assembly_node → approval_chain_node (HUMAN chain)
                  → [reject] rework_edge → proposal_assembly_node
                  → [approve] build_enqueue_node → build_wait_node (event-waiting)
                       → [validation fail] quarantine_node (HUMAN triage)
                       → [ok] human_preview_interrupt → submission_node (HUMAN) → closure_node
        rfi → rfi_node → clarification path
        dealreg_decision → dealreg_update_node → (resume any gate-waiting nodes)
```
Time-waiting nodes (`await_response_node`, `build_wait_node`, gate nodes) are **event-driven**: they park the graph (checkpoint saved, zero resource use) and an **event router** resumes the correct workflow instance when a matching external event arrives.

### 14.3 Resume, retry, idempotency, duplicates
- **Human approval nodes:** graph interrupts; the interrupt id = approval request id in PostgreSQL. The user decision writes the approval row first, then the graph resumes with that input — a service restart loses nothing (the interrupt is a DB row, not process memory).
- **Failed nodes:** per-node retry policy (2× with backoff for model/IO errors; deterministic validation errors go straight to human). Node input/output hashes logged per attempt.
- **Idempotency:** every side-effecting node carries idempotency key = `hash(workflow_id, node_id, input_hash)`; on retry it first checks whether its effect row exists and no-ops (prevents duplicate RFQs, build jobs, audit writes).
- **Duplicate external events:** vendor response insert uses unique key `(opp_id, vendor_id, content_hash)`; the event router drops duplicates before graph resume.
- **Timeouts:** node deadlines (model calls 120 s; builds 600 s); stale graphs swept by the Follow-up Service.
- **Manual override:** admin transition writes an override event; the graph is cancelled and re-anchored at the target state with a new run linked to the old (`workflow_event` rows preserve continuity).
- **Traceability:** every node execution logged (node, started, finished, input/output refs, model_run id) — joins to the audit chain.

---

## 15. PostgreSQL Data Architecture

### 15.1 Schema boundaries
- `core` — opportunity, customer, end_user, contact, requirement, requirement_item, clarification
- `files` — uploaded_file, file_security_event
- `vendors` — vendor, distributor, vendor_contact, vendor_capability, master_version
- `commerce` — rfq(+recipients/versions), deal_registration, vendor_response, quote(+versions/line_items), cost_component, margin_calculation, margin_policy
- `proposals` — technical_solution(+sections/citations), proposal(+versions/payloads), proposal_template, document_build_job, document_validation_result
- `approvals` — approval_rule, approval_request, approval_step, approval_decision
- `workflow` — workflow_instance, workflow_state, workflow_event, task, reminder, comment (+ LangGraph checkpoint tables in `langgraph`)
- `knowledge` — knowledge_document, knowledge_chunk, embedding(vector), retrieval_event
- `ai` — prompt(+versions), model(+versions), model_run, evaluation_dataset/test/result
- `audit` — audit_event (append-only), security_event
- `iam` — user, role, user_role, access_review

### 15.2 Consistency, concurrency, locking
- **Transactions:** multi-entity mutations commit atomically; state transitions and their audit rows in the same transaction — no state without audit.
- **Optimistic locking:** every mutable business row carries `version int`; updates use `WHERE id=? AND version=?`; conflict → 409 + refresh.
- **Unique constraints** enforce idempotency (response content hash, build request hash).
- **Row-level security (RLS)** for customer-level and secure-entity restrictions, enforced by the DB, not the app.

### 15.3 Encryption
- **At rest:** full-disk encryption on VM volumes + `pgcrypto` column encryption for sensitive fields (finance terms, secure-entity details, flagged PII). Keys in OS keystore sealed to the service account.
- **In transit:** TLS 1.2+ between all services (internal CA, §21.1).
- **Backups:** AES-256 encrypted before leaving the VM.

### 15.4 Backup & HA
- `pg_basebackup` nightly + continuous WAL archiving → PITR to any minute within retention.
- Pilot: single primary on VM-1, restore-to-new-VM runbook. Production phase 3+: streaming replica on VM-3 with **manual** failover (auto-failover deliberately out of initial scope — §34).
- **Retention:** business records per policy **[TBC]**; audit events ≥ opportunity lifetime + statutory period; model runs & retrieval events 24 months.

### 15.5 Logical data model
(All review-required entities; compact form — full DDL in implementation phase.)

| Entity (schema) | Purpose | PK | Key fields | Relationships | Indexes | Retention | Sensitivity |
|---|---|---|---|---|---|---|---|
| opportunity (core) | Deal container | id | ref_no, title, status, owner_id, customer_id, value_est | →customer, →user; 1..n requirement/rfq/quote/proposal | status, owner, customer | per policy | internal |
| customer (core) | Direct client org | id | name, code, secure_entity_flag, loc | 1..n opportunity | name (trgm) | permanent | internal |
| end_user (core) | Final beneficiary org | id | name, customer_id, secure flag | n..1 customer | name | permanent | restricted |
| contact (core) | People | id | name, role, email, phone, org_id | →customer/end_user | org | per policy | PII |
| user (iam) | Platform user | id | upn, display, active | n..n role | upn | employment+1y | internal |
| role (iam) | RBAC roles | id | name, permissions jsonb | n..n user | name | permanent | internal |
| requirement (core) | Versioned requirement | id | opp_id, version, source_type, file_ref | n..1 opportunity | opp | per policy | internal |
| requirement_item (core) | Individual asks | id | req_id, brand, model, qty, tech | n..1 requirement | req | per policy | internal |
| uploaded_file (files) | Immutable originals | id | content_hash, mime, size, path, opp_id | →opportunity | hash unique | per policy | may be sensitive |
| extracted_field (core) | AI field output | id | opp_id, field, value, status, confidence, model_run_id | →model_run | opp | per policy | internal |
| clarification (core) | Q&A tracking | id | opp_id, question, answer, state, due | n..1 opp | opp, state | per policy | internal |
| vendor (vendors) | OEM org | id | name, domains[] | 1..n capability/contact | name | permanent | internal |
| distributor (vendors) | Disti org | id | name | 1..n contact | name | permanent | internal |
| vendor_contact (vendors) | Vendor people | id | vendor_id, name, email, class | n..1 vendor/disti | vendor | per policy | PII |
| vendor_capability (vendors) | Coverage | id | vendor_id, domain, brand, tier | n..1 vendor | domain, brand | permanent | internal |
| rfq (commerce) | RFQ container | id | ref_no, opp_id, status | 1..n recipient/version | opp, status | per policy | internal |
| rfq_recipient (commerce) | RFQ targets | id | rfq_id, vendor_id, class, include_enduser | n..1 rfq | rfq | per policy | internal |
| rfq_version (commerce) | Draft versions | id | rfq_id, version, body, approved_by | n..1 rfq | rfq | per policy | internal |
| deal_registration (commerce) | Gate record | id | opp_id, vendor_id, ref, status, expiry | n..1 opp | opp, status | per policy | commercially sensitive |
| vendor_response (commerce) | Pasted replies | id | opp_id, vendor_id, class, content_hash | n..1 opp | unique(opp,vendor,hash) | per policy | internal |
| quote (commerce) | Quote container | id | ref, opp_id, vendor_id, status | 1..n version | opp | per policy | sensitive |
| quote_version (commerce) | Revisions | id | quote_id, version, valid_until | n..1 quote | quote | per policy | sensitive |
| quote_line_item (commerce) | Lines | id | qv_id, desc, qty, unit, total | n..1 quote_version | qv | per policy | sensitive |
| cost_component (commerce) | Freight/PM/etc | id | quote_id, type, amount, actor | n..1 quote | quote | per policy | finance-restricted |
| margin_calculation (commerce) | Margin math | id | quote_id, sell, cost, margin_pct | 1..1 quote | quote | per policy | finance-restricted |
| technical_solution (proposals) | TP content set | id | opp_id, status | 1..n section | opp | per policy | internal |
| proposal (proposals) | CP/TP/AMC record | id | opp_id, type, status, template_version | 1..n version | opp | per policy | sensitive |
| proposal_version (proposals) | Generated files | id | proposal_id, version, docx_ref, pdf_ref, payload_hash | n..1 proposal | proposal | per policy | sensitive |
| proposal_template (proposals) | Golden registry | id | type, version, file_ref, sha256, registered_by | 1..n proposal | type+version unique | permanent | internal |
| approval_rule (approvals) | Matrix config | id | condition jsonb, chain jsonb, active | — | active | permanent | internal |
| approval_request (approvals) | Chain instance | id | opp_id, rule_id, state, payload_hash | 1..n step | opp, state | per policy | internal |
| approval_step (approvals) | One step | id | request_id, seq, approver_role, mode | 1..1 decision | request | per policy | internal |
| approval_decision (approvals) | Decision | id | step_id, approver_id, decision, reason, evidence, at | n..1 step | approver | per policy | internal |
| workflow_instance (workflow) | Graph run | id | opp_id, graph, state, started | n..1 opp | opp | per policy | internal |
| workflow_state (workflow) | Current node | id | instance_id, node, parked_reason | 1..1 instance | instance | per policy | internal |
| workflow_event (workflow) | Transitions/overrides | id | instance_id, event, actor, payload | n..1 instance | instance | per policy | internal |
| task / reminder (workflow) | Work items | id | owner_id, kind, due, state | →opp | owner, due | 24 mo | internal |
| comment (workflow) | Notes | id | opp_id, author, body | n..1 opp | opp | per policy | internal |
| audit_event (audit) | Hash-chained log | id | ts, actor, action, entity, payload_hash, prev_hash, hash | — | entity, ts | ≥ opp lifetime+statutory | restricted |
| knowledge_document (knowledge) | Approved corpus | id | title, type, status, version, owner, expiry | 1..n chunk | status, type | versioned | mixed |
| knowledge_chunk (knowledge) | Chunks | id | doc_id, seq, text, section_ref | n..1 doc | doc | versioned | mixed |
| embedding (knowledge) | Vectors | id | chunk_id, vector(1024), model | 1..1 chunk | hnsw | versioned | internal |
| retrieval_event (knowledge) | Retrieval audit | id | opp_id, query, chunk_ids, scores, at | →opp, →chunks | opp, ts | 24 mo | internal |
| prompt / prompt_version (ai) | Prompt registry | id / (prompt_id,version) | name, text, vars | 1..n version | name | permanent | internal |
| model / model_version (ai) | Model registry | id | name, ollama_tag, sha256, size | 1..n version | name | permanent | internal |
| model_run (ai) | Every invocation | id | model_ver, prompt_ver, latency, tokens, status, node | →model, →prompt | ts | 24 mo | internal |
| evaluation_dataset/test/result (ai) | Benchmarks | id | name / input, expected / metrics, pass | — | dataset | permanent | internal |
| security_event (audit) | Security log | id | ts, kind, actor, detail | — | kind, ts | 24 mo | restricted |
| document_build_job (proposals) | Build queue | id | proposal_id, request_hash, state, attempts | n..1 proposal | state; request_hash unique | per policy | internal |
| document_validation_result (proposals) | QA report | id | job_id, checks jsonb, pass | 1..1 job | job | per policy | internal |

---

## 16. RAG and Knowledge Architecture

### 16.1 Engine choice: **pgvector inside PostgreSQL** (recommended over Qdrant)
**Why:** one less moving part in an air gap (no second DB to secure, patch, back up, monitor); vectors live **transactionally beside** the documents and approval metadata they belong to — retrieval filters (approval status, customer/vendor restrictions, expiry) are SQL joins, not application stitching; one backup covers content + embeddings; pgvector HNSW is sufficient at this corpus scale (thousands of documents, not millions). **Qdrant wins** only at >~1M chunks or heavy vector QPS — not this system's shape. Decision recorded in §31; reversible via the chunk/embedding abstraction.

### 16.2 Content classes (hard separation via `status` + `content_class`)
1. **Approved** — the only class retrievable for customer-facing drafting (default SQL filter; prompts cannot relax it).
2. **Draft** — retrievable by authors/admins only; never in proposal context.
3. **Historical reference** — past approved proposals; retrievable, citations flagged "historical".
4. **Vendor-provided** — datasheets; citations marked "vendor source"; never quoted as a NationLabs commitment.
5. **Customer-provided** — scoped to that customer's opportunities (RLS).
6. **AI-generated temporary** — never ingested; lives only as draft entities outside RAG.

### 16.3 Pipeline
- **Ingestion:** controlled media or admin upload → file security pipeline (§21.3) → parsers (DOCX/PDF/XLSX; OCR in a later phase).
- **Metadata & classification:** type (terms/datasheet/solution brief/historical proposal/clause/SOP/email wording/deal-reg language), owner, source, dates; 4b classifier suggests `content_class`; **human approval** sets `status=approved` — ingestion never self-approves.
- **Chunking:** structure-aware (headings/sections, 400–800 tokens, ~15% overlap; tables kept whole; section refs preserved for citations).
- **Embeddings:** local on the A30 — `bge-m3` (multilingual incl. Arabic, 1024-dim) via Ollama — benchmarked against `nomic-embed-text` (§26).
- **Indexing:** pgvector HNSW + Postgres tsvector for keywords; metadata indexed (status, class, vendor, customer, expiry).
- **Hybrid retrieval:** metadata pre-filter (approval/ACL/expiry at SQL layer) → vector ∪ keyword, RRF fusion → local reranker (bge-reranker-v2-m3) → top-k with scores.
- **Citations:** every chunk carries {source document, version, approval status, section/page ref, retrieval score, date, owner}; citations render inline in the drafting UI; `retrieval_event` logs query→chunks→scores per opportunity.
- **Governance:** versioning (new version supersedes; superseded retained but excluded from default retrieval); expiry auto-demotes to draft; owner review reminders; retrieval access control by role + customer/vendor restrictions; **no silent use of unapproved content — structurally impossible** (SQL-layer filter).

---

## 17. AI Model Architecture

### 17.1 Model Gateway (all calls through here)
- Queue with per-model concurrency limits (GPU serialization), deadlines, retries (2× backoff), circuit breaker on repeated malformed output, full `model_run` logging (model version, prompt version, latency, tokens, caller node, status).
- **Version pinning:** prompts and models referenced by immutable version ids — every AI output traceable to exact prompt+model.
- **Ollama now** (matches the existing VM, ops-simple, offline model import via media); **vLLM evaluated in Phase 2** if §26 throughput data justifies it (continuous batching vs added ops complexity — §31).

### 17.2 Model roles (subject to §26 acceptance)
| Role | Model (current) | Notes |
|---|---|---|
| Extraction, classification, drafting, RAG-grounded writing | qwen3:14b | JSON-schema-constrained decoding; temperature≈0 for extraction |
| Fast rails (reply triage, injection screening, field sanity) | gemma3:4b | sub-second; flags for 14b/human, never final authority |
| Embeddings | bge-m3 (to benchmark) | local, multilingual incl. Arabic |
| Reranking | bge-reranker-v2-m3 (to benchmark) | optional quality layer |

### 17.3 AI safety patterns
Structured outputs via JSON schema; payload quarantine delimiters + data-only system prompts; 4b injection screen on all pasted external text; no tool execution from model text (models return data, code executes); confidence floors routing to humans; temperature 0 for anything feeding numbers; **numbers from models are never trusted — re-derived deterministically**.

---

## 18. Proposal Builder Integration

**Principle: reuse, don't rebuild.** The existing NationLabs proposal builder (already proven to produce the golden format, including the COM-based golden-exact path demonstrated in this engagement) is wrapped as an internal service. The AI orchestrator never touches a Word document directly.

### 18.1 API contract (internal REST, doc-worker zone)
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/builds` | Create build job `{type: cp|tp|amc, template_version, payload, payload_hash}` → `{job_id}` |
| POST | `/api/v1/builds/validate` | Validate payload against template requirements without building → `{valid, errors[]}` |
| GET | `/api/v1/builds/{id}` | Job state: queued/running/validating/done/quarantined + error detail |
| GET | `/api/v1/builds/{id}/artifacts` | `{docx_ref, pdf_ref, validation_report_ref, metadata}` |
| GET | `/api/v1/templates` | Registered template versions + hashes |
| GET | `/api/v1/health` | Service + COM worker health |

### 18.2 Responsibility split
- **Orchestrator → builder:** only approved, validated, frozen structured data (payload + hash). Content changes after approval = new payload hash = new build, linked as a new proposal version.
- **Builder owns:** golden template handling, fonts, table layouts, headings, BOQ placement, costing-sheet placement, Excel EMF image creation/placement, page layout, headers/footers, branding, final DOCX formatting, PDF rendering.

## 19. Windows Document Worker Design

### 19.1 Isolation & hardening
- Dedicated Windows Server 2022 VM, **licensed MS Office**, dedicated low-privilege service account (no domain admin, no interactive logon except admin break-glass), firewall allows only orchestrator ↔ worker API flow, **no internet gateway**, no shared drives except its own artifact store, Office macros disabled by policy, Protected View enforced for any opened foreign file.
- Templates stored locally, registered with SHA-256 in the template registry; service refuses to start on hash mismatch; rollback = re-register previous version (files immutable per version).

### 19.2 Build execution model
- **Serial queue, one COM worker per build session.** Worker lifecycle per job: fresh WINWORD/EXCEL processes → build → validate → hard-kill any process it spawned (orphan cleanup by PID tracking) → report. Watchdog supervisor: job timeout (default 600 s), **Office dialog detection** (window-title scanning for modal dialogs → auto-dismiss log + kill), crash → retry once on a clean COM instance → quarantine with full logs and the input payload.
- **Idempotency:** `request_hash = hash(type, template_version, payload)`; duplicate submission returns the existing job. **Content-hash duplicate detection** prevents rebuilds of identical payloads.
- Health: heartbeat to orchestrator; queue depth, job age, COM failure rate exported as metrics (§23).

### 19.3 Malware & macro controls
Templates are the only documents ever opened, and only from the registry; payloads are pure data (JSON), never documents; generated outputs are created, never opened from external sources; macro-bearing templates are rejected at registration.

### 19.4 Automated document-quality validation (runs on the worker post-build)
- **Structural (DOCX package):** no residual `{{placeholder}}` tokens; required sections present in order (per template type); correct fonts/sizes spot-checked against the golden's style map; headers/footers present; page count within expected band; no blank pages; table grid integrity; images present at required anchors (BOQ, costing); file opens cleanly (python-docx + Word COM double check).
- **Numeric:** totals/VAT in the rendered document **re-extracted and compared** to the approved payload (independent re-check of what the customer will actually see).
- **References/version:** template version stamped; TOC field present (flag: "update field in Word" instruction for final human preview step).
- **PDF:** generated via Word's own export; page count parity with DOCX; text-extractable.
- **Visual regression (recommended, phased in):** render every PDF page to an image (pypdfium2 or Word COM), compare against the golden reference *structure* — per-page region layout fingerprints (heading bands, table bounding boxes, image slots) rather than pixel-perfect diff (content legitimately varies per deal). Thresholds tuned during pilot; today this is proven feasible (page renders were produced during the engagement). Failures route to quarantine + human preview with diff highlights.

## 20. API Architecture

OpenAPI-first, versioned (`/api/v1`), JSON, TLS, service-to-service via mTLS in phase 3+. Conventions: `Idempotency-Key` header on all POSTs with side effects; `409` on optimistic-lock conflict; problem+json errors; every mutating call emits an audit event.

| Group | Key endpoints (method + path) |
|---|---|
| Opportunity | `POST /opportunities` · `GET /opportunities/{id}` · `PATCH /opportunities/{id}` · `POST /opportunities/{id}/files` |
| Intake/files | `GET /files/{id}` (download-logged) · `POST /files/{id}/rescan` |
| Extraction | `POST /opportunities/{id}/extract` · `POST /opportunities/{id}/verify_extraction` |
| Classification | `POST /opportunities/{id}/classify` · `POST /opportunities/{id}/classification/override` |
| Clarification | `POST /opportunities/{id}/clarifications` · `POST /clarifications/{id}/answer` |
| Vendor | `GET /vendors` · `POST /opportunities/{id}/match_vendors` · `POST /opportunities/{id}/vendors/validate` |
| RFQ | `POST /opportunities/{id}/rfqs/draft` · `POST /rfqs/{id}/approve` · `POST /rfqs/{id}/confirm_sent` · `GET /rfqs/{id}/versions` |
| Deal-reg | `GET /opportunities/{id}/deal-registration` · `POST /deal-registrations/{id}/status` · `POST /deal-registrations/{id}/override` (elevated) |
| Response | `POST /rfqs/{id}/responses` · `POST /responses/{id}/classify` · `POST /responses/{id}/reclassify` |
| Quote | `POST /quotes/extract` · `POST /quotes/{id}/validate` · `GET /quotes/{id}/validation` |
| Costing | `POST /quotes/{id}/costing` · `GET /quotes/{id}/margin` |
| Approval | `POST /opportunities/{id}/route` · `GET /approvals?assignee=me` · `POST /approvals/{id}/decision` |
| Proposal | `POST /proposals/{type}/assemble` · `POST /proposals/{id}/build` · `GET /proposals/{id}/artifacts` · `POST /proposals/{id}/preview_decision` |
| Workflow | `GET /workflow/{opp_id}` · `POST /workflow/{opp_id}/pause` · `POST /workflow/{opp_id}/resume` · `POST /workflow/{opp_id}/override` (admin) |
| Audit | `GET /audit/{entity}/{id}` · `POST /audit/verify` (admin) |
| Knowledge | `POST /knowledge/documents` · `POST /knowledge/documents/{id}/approve` · `POST /knowledge/search` · `GET /knowledge/retrievals/{opp_id}` |
| Admin | CRUD `/admin/users` · CRUD `/admin/approval-rules` · `POST /admin/templates` · `GET /admin/config` |
| Evaluation | `POST /eval/datasets` · `POST /eval/runs` · `GET /eval/runs/{id}` |

**AuthN/Z per call:** session (AD-bound or local) + role check + object-level check (ownership/customer restriction/RLS). Example: `POST /approvals/{id}/decision` — authn required; authz = step assignee or delegate; idempotency = one decision per step; validation = decision ∈ {approve,reject}, reason mandatory on reject; error = 409 if step already decided; audit = `approval_decision`.

## 21. Security Architecture

### 21.1 Network security
- Zones (§9): user, ai-app, doc-worker, data, backup, admin, controlled-update. Default-deny firewalls (hypervisor-level virtual switches + host firewalls). Allow-list examples: user→orchestrator 443; orchestrator→doc-worker 8443; orchestrator→PostgreSQL 5432 (localhost-only in MVP); backup→NAS; admin→jump host only.
- **No default internet gateway** on any zone. Internal DNS (forwarders disabled), internal NTP (host as source), **internal CA** issuing service certificates; TLS 1.2+ on every service hop, mTLS between orchestrator and doc-worker in phase 3+.

### 21.2 Identity & access
- **AD/LDAP preferred** if available in-gap **[TBC D4]**; else local accounts with Argon2 hashing, 12+ char policy, lockout (5 attempts/15 min), session timeout 30 min idle, MFA via TOTP for admin role (offline TOTP apps work in air gap).
- RBAC roles: presales member, presales lead, finance, technical reviewer, legal, approver (manager/CEO/TAL), admin, auditor (read-only). Least privilege per module API.
- Object-level: opportunity ownership + team visibility; **customer-level restrictions**; **secure-entity**: deals flagged secure-entity visible only to explicitly listed users (RLS); finance-only fields (margins, costs) masked for non-finance roles; maker-checker on approvals (approver ≠ drafter); quarterly access review (report generated); deactivation immediate (session revocation); **all downloads/exports audit-logged**.

### 21.3 File security pipeline (every upload, before any processing)
extension allow-list → MIME check → **magic-byte verification** → size cap (50 MB default) → **ClamAV scan** (locally deployable, offline definition updates via controlled media; complemented by YARA rules for office-macro heuristics) → macro detection in Office files (oletools); macros stripped when policy permits else quarantine → embedded-object inventory → archive expansion scan (depth-limited) → PDF active-content flag (JavaScript/AA entries → strip or quarantine) → SHA-256 hash + duplicate detection → immutable storage → `file_security_event` logged. Failures quarantine with owner notification; quarantined items reviewable by admin only.
**Recommended local AV:** ClamAV (offline-capable, scriptable, free) + YARA; alternative: a licensed offline engine (e.g., ESET/Bitdefender offline scanner) if procurement prefers — interface is abstracted.

### 21.4 Data protection
Encryption at rest (FDE on VM volumes), pgcrypto for sensitive columns, AES-256 encrypted backups, TLS in transit, access + download logging, retention per policy **[TBC D7]** incl. customer-specific overrides, secure deletion (crypto-erase via key destruction for encrypted stores; overwrite for media sanitization), backup retention 30 daily + 12 monthly, **controlled removable-media process**: single update station, checksum verification (SHA-256 manifest) for all offline updates (models, AV definitions, OS packages, templates), media scanned before mount, all transfers logged.

### 21.5 AI security
Prompt-injection & **indirect** injection defense (pasted vendor/customer text is the main vector): payload delimiters + data-only system prompts; 4b injection screen → flag to human; JSON-schema structured outputs with strict validation; tool allow-listing (models have no tools — they return data; application code executes); **no arbitrary command/code execution from model output, ever**; retrieval access enforced at SQL layer; sensitive-data filtering on outbound drafts (end-user details only to OEM/Distributor class, code-enforced); hallucination controls (grounding + confidence floors + human gates); prompt & model version control (immutable versions, eval-gated changes); **malicious-vendor-reply test suite** part of §26 regression.

### 21.6 Monitoring (security)
Application logs, security event log, auth failures, workflow errors, doc-build failures, quarantine events, privileged activity, abnormal download behaviour (volume/velocity rules), model invocation logs — all shipped to Loki; alerting rules in Grafana; **Wazuh** (local, open-source SIEM) recommended for host-level HIDS + log correlation on both VMs when ops capacity allows (phase 3).

## 22. Audit and Compliance

- **Append-only, hash-chained `audit_event`:** each row includes `prev_hash`; daily verification job walks the chain; mismatch → critical alert + service refuses sensitive operations.
- Covered events: every state transition, approval decision, override (with reason + elevated actor), retrieval, model run reference, build job, download/export, template registration, master-data change, login/auth failure.
- Reports: per-opportunity evidence pack (one click: full history, approvals, generated versions, retrieval citations); auditor role read-only; export via controlled media only.

## 23. Observability

**Stack (all local, offline-friendly): Prometheus + Grafana + Loki + node_exporter + DCGM/nvidia GPU exporter + blackbox-style health probes.** (OpenSearch evaluated as Loki alternative if free-text log search demand grows; Prometheus/Grafana/Loki chosen for lowest ops weight.)

**Metrics:** service health, CPU/RAM/disk per VM, GPU utilisation + VRAM, model latency p50/p95, model queue depth, API latency/error rates, PostgreSQL health (connections, locks, replication lag when applicable), vector-search latency, workflow backlog + stuck count, overdue approvals, overdue vendor follow-ups, doc-build queue depth, COM failure rate, malware-scan failures, backup success/age, audit-chain verification status, certificate expiry, template integrity status.

**Operational dashboard layout (Grafana, single pane):** top row = platform health (VMs, DB, GPU, doc-worker); second = pipeline (opportunities by state, aging, stuck workflows); third = SLAs (approvals overdue, vendor follow-ups due, build queue); fourth = AI (model latency/VRAM/queue, malformed-output rate); bottom = security & compliance (audit-chain OK, backups, quarantine, cert expiry, auth failures).

**Alerting:** page-worthy = audit-chain failure, backup failure, doc-worker down >15 min, DB down; ticket-worthy = stale workflows, SLA breaches, malformed-output spike.

## 24. Backup, DR and Business Continuity

**Business impact analysis:** this system holds pipeline revenue work, commercial commitments, and legal-grade audit evidence. Worst tolerable loss = one business day of manual re-entry (RPO 24 h, tighten to 1 h once WAL archiving to NAS proven); worst tolerable outage = 2 business days before presales reverts to manual process (RTO 48 h; target 8 h with rehearsed restore).

| Item | Method | Frequency | Retention |
|---|---|---|---|
| PostgreSQL | pg_basebackup + WAL archive (PITR) | nightly base + continuous WAL | 30 daily + 12 monthly |
| File store (originals, proposals) | rsync to NAS, encrypted | nightly | same |
| Knowledge base + vector index | with DB backup; re-embedding runbook documented | nightly | same |
| Golden templates | registry + immutable copies, hashed | on change | permanent |
| Model files | offline copy on NAS (Ollama blobs) | on change | permanent |
| LangGraph checkpoints | inside DB backup | continuous | same |
| Audit chain | inside DB + monthly export to offline media (signed manifest) | monthly | ≥ statutory |
| Doc-worker config | VM image snapshot + config export | weekly | 4 weekly |

All backups AES-256-encrypted; offline rotation copy via controlled media weekly. **Integrity:** monthly automated restore-test to an isolated VM + boot check; quarterly full DR drill with runbook (restore order: DB → file store → app → doc-worker → verification queries → audit-chain walk). **Ownership:** restore = NationLabs IT; verification = platform admin; drill results logged.

---

## 25. Failure Modes

| # | Failure | Detection | Handling / recovery |
|---|---|---|---|
| F1 | Ollama down / GPU fault | health probe, call failures | Model Gateway circuit breaker; AI nodes park; **manual-degraded mode** (workflow still advances; AI steps marked manual-override in audit); alert |
| F2 | Model timeout under load | gateway deadline | retry 2× backoff; queue; user-visible "AI busy"; never hangs a state |
| F3 | Malformed model JSON | schema validation | strict-prompt retry; 2 failures → human with raw payload |
| F4 | Hallucinated extraction | Confirmed/Missing + confidence + verification gate | user verifies fields pre-RFQ; mislabels feed eval set |
| F5 | Reply misclassification | confidence floor; downstream absence (e.g., no line items) | manual reclassify; example added to regression suite |
| F6 | Prompt injection in vendor text | 4b screen + schema reject + anomaly flags | payload quarantined as data; human notified; injection test-suite updated |
| F7 | Duplicate quote / event | unique constraint on content hash | reject with link to existing record |
| F8 | Quote arithmetic mismatch (vendor error) | deterministic validator | discrepancy report; never auto-correct vendor numbers; clarification RFI drafted |
| F9 | Deal-reg expires before quote | daily scan | owner alert + renewal draft; gate stays closed |
| F10 | COM crash / Office dialog hang | worker watchdog + dialog detection | kill by PID tracking; retry once clean; quarantine + alert; state stays `BUILDING`, never advances on partial output |
| F11 | Build queue stuck | heartbeat + job age | service auto-restart (service manager); idempotent jobs resume |
| F12 | Template tampering/drift | startup hash check + registry | builds refused; alert; rollback to previous registered version |
| F13 | DB corruption | boot integrity check + backup verification | PITR restore; audit-chain walk distinguishes corruption from tampering |
| F14 | Audit chain mismatch | daily verification | critical alert; sensitive operations suspended pending investigation |
| F15 | Concurrent edit conflict | optimistic locking version check | 409 + refresh; no silent overwrite |
| F16 | Stale workflow (parked too long) | Follow-up sweep | escalate to owner + lead; auto-park only, never auto-close |
| F17 | Approval SLA breach | SLA monitor | reminder → escalation per matrix |
| F18 | Backup failure | job monitoring | alert; daily re-run; restore-test failures block release |
| F19 | Clock skew | single NTP (host) | all timestamps from DB clock |
| F20 | Certificate expiry | expiry metric (30/14/7-day warnings) | internal CA reissue runbook |
| F21 | Knowledge doc expires mid-use | expiry demotion job | excluded from retrieval; owner reminded; proposals already built remain valid (version provenance recorded) |
| F22 | Malicious macro in upload | file pipeline (ClamAV+YARA+oletools) | quarantine; admin review; security event |
| F23 | Doc-worker VM down | health probe | builds queue (durable); deals progress to `READY_FOR_BUILD` and wait; alert |
| F24 | Operator error (wrong data) | verification gates + audit trail | rework transitions return to the correct stage; audit preserves full history |

## 26. Benchmark and Evaluation Plan

### 26.1 Evaluation dataset
**30–50 historical NationLabs opportunities** (collected Phase 0): RFP texts, verbal/WhatsApp notes, RFQs, vendor responses (quotes, revised quotes, deal-reg approvals/rejections/conditions, RFIs), CPs, TPs, AMC proposals. Labeled by presales leads (field-level extraction truth, classifications, reply classes). Malicious set: ≥10 crafted injection attempts in fake vendor replies.

### 26.2 Metrics and production acceptance thresholds **[initial values — confirm after first baseline]**
| Metric | Threshold |
|---|---|
| Field extraction accuracy (key fields) | ≥ 95% |
| Requirement-item extraction F1 | ≥ 0.90 |
| Classification (opp/proposal/domain) F1 | ≥ 0.90 |
| Missing-information detection recall | ≥ 0.90 |
| Vendor matching top-3 hit rate | ≥ 95% |
| Reply classification accuracy | ≥ 92% |
| Quote line-item extraction accuracy | ≥ 97% (mandatory: deterministic validation backstop) |
| Quote arithmetic error rate (system) | 0% (deterministic — not model-dependent) |
| Hallucination (unsupported facts in drafts) | 0 tolerated in customer-visible output (human gate + citation check) |
| Citation correctness (RAG) | ≥ 98% chunks correctly attributed |
| JSON parse success (with one retry) | ≥ 99% |
| Prompt-injection test pass | 100% (no instruction executed, all flagged or neutralised) |
| Latency p95: classification ≤ 15 s; extraction ≤ 45 s; draft section ≤ 60 s | on A30 |
| GPU VRAM steady-state | ≤ 22 GB (2 GB headroom) |

### 26.3 Candidates
qwen3:14b (incumbent), gemma3:4b (rails), plus any locally deployable ≤24 GB challenger (e.g., Mistral/Qwen variants) **only if data shows a gap** — no model is chosen for being bigger. Embedding: bge-m3 vs nomic-embed-text.

### 26.4 Regression policy
Full suite re-run after any change to: model version, prompt version, embedding model, RAG config, template version, workflow graph. Gate: no release with a threshold regression; results stored in `evaluation_result` with the exact versions under test; trend dashboard in Grafana.

## 27. Infrastructure Sizing

### 27.1 Validation of the existing estate
The R750 (48 cores / 128 GB / A30) is **sufficient for MVP and pilot** with room to spare, provided memory is apportioned honestly (below).

### 27.2 Ubuntu AI VM (VM-1)
| Resource | MVP | Production |
|---|---|---|
| vCPU | 16 | 24 |
| RAM | 56 GB | 72 GB (Ollama host 8–12, PostgreSQL 16–24, app 8, monitoring 4, OS/cache rest) |
| Disk | 1 TB | 1.5–2 TB (files, backups staging, logs) |
| GPU | A30 passthrough | same; **2nd A30/A40 when §27.4 triggers** |
| OS/runtime | Ubuntu 22.04 LTS, Docker + compose | same |
| Inference | Ollama | Ollama (vLLM only if §26 justifies) |
| DB | PostgreSQL 16 + pgvector, **same VM** | same VM initially; replica VM phase 3+ |
| Redis | **not required** (queues in PostgreSQL/LangGraph) | add only if cache/queue profiling demands |
| Vector DB | **pgvector in PostgreSQL** (no separate service) | same |
| Monitoring | Prometheus, Grafana, Loki, exporters | same + Wazuh phase 3 |

### 27.3 Windows Document Worker VM (VM-2)
4 vCPU · 16 GB RAM · 250 GB · Windows Server 2022 · **MS Office licensed** · dedicated service account · queue capacity 50 jobs (ample: builds are serial, minutes each) · weekly VM snapshot backup.

**Co-location decision:** PostgreSQL, (no Redis), pgvector all on the AI VM for MVP/pilot — fewer VMs to secure and back up inside the air gap; split only when §27.4 or HA phase arrives.

### 27.4 Can one A30 24 GB cope?
Workload reality: 5–10 users, tens of deals/month, AI calls in seconds each, serialized by the Model Gateway. qwen3:14b (~9–10 GB VRAM quantized) + gemma3:4b (~3 GB) + embeddings (~2 GB) ≈ 15 GB — fits with headroom. Expect **effective concurrency 1–2 heavy calls**; user-visible waits appear only if several extractions/drafts collide (queue absorbs; p95 targets in §26).
**Add a 2nd GPU (chassis-ready) or a separate inference VM when:** sustained model queue depth > 4 during business hours for a week, p95 extraction > 60 s, or > 15 concurrent users onboard.

### 27.5 Layouts
- **MVP:** VM-1 (all-in-one app+DB+models+monitoring) + VM-2 (doc worker) + NAS backup.
- **Pilot:** + Wazuh, hardened IAM, restore-tested backups.
- **Production:** + VM-3 PostgreSQL standby (manual failover), mTLS service-to-service, DR drills.
- **Future HA:** 2nd GPU / inference VM, Postgres auto-failover (Patroni), second doc-worker with queue sharding (still serial per worker).

## 28. Rollout Roadmap

Effort in person-weeks (pw), assuming 1 lead engineer + part-time Raghu + reviews. No calendar dates without confirmed team size **[TBC]**.

| Phase | Deliverables | Dependencies | Exit criteria | Key risks | Responsible | Effort |
|---|---|---|---|---|---|---|
| 0 Discovery & Validation | confirmed workflow, approval matrix, golden templates (CP/TP/AMC), builder inventory, prototype review, COM proof validated, vendor master cleansed, eval dataset collected, acceptance criteria signed | access to history; Niren time | all D-decisions answered or scheduled | decisions stall; dataset scarcity | Raghu + Niren | 2–3 pw |
| 1 Platform Foundation | PostgreSQL schemas, auth+RBAC, opportunity mgmt, file intake+security pipeline, audit framework, workflow persistence, LangGraph base, model gateway | Phase 0; VM-1 provisioned | intake→audit e2e test green; restart-resume proven | schema churn | Lead eng | 4–6 pw |
| 2 Presales Workflow | extraction, classification, readiness, clarification, matching, RFQ drafting, deal-reg tracking, response processing, follow-ups | Phase 1 | pilot deal reaches RFQ_SENT end-to-end; §26 rail metrics baseline | extraction quality below threshold | Lead eng + Raghu | 4–6 pw |
| 3 Quote & Commercial | quote extraction/validation, revisions, costing, margin, approval engine | Phase 2 | quote→validated→routed with matrix; math zero-error proven | approval matrix ambiguity | Lead eng | 3–4 pw |
| 4 Knowledge & TP | RAG ingestion, approved library, citations, TP drafting + review | Phase 1; content authors (D5) | TP draft with correct citations; unapproved-content test passes | library authoring effort underestimated | Presales leads + eng | 3–5 pw |
| 5 Proposal Builder Integration | builder API, doc-worker hardened, CP/TP/AMC builds, DOCX+PDF validation, visual regression (phased) | D2 (VM+Office); D3 (AMC golden) | golden-format outputs pass structural+visual QA; quarantine path proven | COM flakiness; AMC template gaps | Lead eng | 4–6 pw |
| 6 Pilot | 2–5 live opportunities, shadow validation, defect burn-down, benchmark reruns, security test, restore test | Phases 1–5 | zero critical defects; thresholds met; users trained | real-world edge cases | Raghu + pilot users | 3–4 pw |
| 7 Production | onboarding, SOPs, admin guide, runbook, DR drill, acceptance sign-off, controlled go-live | Phase 6 | §33 acceptance criteria all green; Niren format sign-off | operational discipline | All | 2–3 pw |

## 29. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Office/VM procurement delayed (D2) | medium | blocks Phase 5 | decide in Phase 0; interim: controlled desktop build station (documented, audited) — explicitly temporary |
| Extraction quality below threshold | medium | manual workload stays high | benchmark early (Phase 0 dataset), prompt iteration, rail-model triage, human-verify gate is always on |
| COM instability at scale | medium | build delays | watchdog/quarantine/retry design (§19); visual QA backstop; builds are async and never block deal progress |
| Approval matrix never finalized | medium | Phase 3 stall | ship with default chain + safe fallback; matrix editable by admin without release |
| Content library authoring fatigue | medium | TP quality varies | start with top 5 technologies by deal volume; historical proposals seed the library (approved by Niren) |
| Air-gap update lapses (AV defs, models) | medium | security drift | controlled-media SOP with checksums + monthly calendar reminder |
| Scope creep ("also auto-send emails") | high | violates core principle | architecture constitution: no autonomous external sends; change requires written sign-off |
| Key-person dependency (Raghu) | medium | delivery risk | docs, runbooks, admin guide from Phase 1; Niren visibility via dashboards |
| Data retention/legal ambiguity (D7) | low-medium | compliance exposure | conservative defaults until policy; audit retained longest |

## 30. Assumptions

1. Windows VM + licensed Office will be procured (D2). 2. AD/LDAP may exist in-gap (D4); local auth is the fallback. 3. Vendor master will be cleansed in Phase 0. 4. AMC follows the golden format family (D3 — unverified). 5. Users ≤ 10 concurrent in year 1. 6. Historical data for the eval set exists and is shareable. 7. Internal SMTP may exist for notifications (D6) — follow-ups work without it (UI tasks). 8. Workstation browsers are modern (TLS 1.2+). 9. Retention/legal policy will be supplied (D7). 10. The existing proposal builder's source/behavior can be wrapped as-is (Phase 0 inventory confirms).

## 31. Decisions Requiring Raghu or Niren Approval

| Decision | Recommended | Alternative | Reason | Risk of recommendation | Owner | Approval needed | Deadline |
|---|---|---|---|---|---|---|---|
| PostgreSQL vs SQLite | **PostgreSQL** | SQLite | mandated; concurrency, RLS, pgvector, PITR | more ops | Architect | Ratify | Phase 0 |
| pgvector vs Qdrant | **pgvector** | Qdrant | one less service; ACL joins; one backup | ceiling at huge corpus (not ours) | Architect | Ratify | Phase 1 |
| LangGraph vs custom engine | **LangGraph** | custom | mandated-preferred; checkpointing, HITL primitives | framework learning curve | Architect | Ratify | Phase 1 |
| Ollama vs vLLM | **Ollama → vLLM if §26 says so** | vLLM now | ops simplicity; offline model import | throughput ceiling later | Architect | Ratify | Phase 2 |
| React vs server-rendered UI | **server-rendered** | React SPA | no npm supply chain in air gap; auditability | less flashy UX | Architect | Ratify | Phase 1 |
| Existing builder vs rebuild | **Reuse existing** | rebuild | mandated; proven golden fidelity | hidden builder limitations (Phase 0 inventory) | Niren | Yes | Phase 0 |
| Office COM vs non-Office generation | **Office COM (hardened worker)** | LibreOffice/python-docx | only zero-deviation path (proven) | unattended-COM fragility (mitigated §19) | Niren + IT | Yes | Phase 0 |
| AD vs local accounts | **AD if available (D4)** | local | central identity, reviews | AD may not exist in-gap | IT | Yes | Phase 0 |
| Single VM vs multiple | **2 VMs (AI + doc-worker)** | 4+ VMs now | minimal attack surface, honest sizing | consolidation risk (backups/DR mitigate) | Architect | Ratify | Phase 0 |
| Redis requirement | **Defer** | deploy Redis | Postgres covers queues/cache at our scale | add later if profiling says so | Architect | Ratify | Phase 1 |
| MinIO vs NAS file storage | **NAS (existing)** | MinIO | no extra service; NAS already in-gap | object-API conveniences lost | IT | Yes | Phase 0 |
| Windows worker licensing | **License Office on VM-2** | desktop station (temp only) | production requirement D2 | procurement time | IT/Niren | Yes | Phase 0 |
| Backup target | **Existing NAS + offline media rotation** | new backup appliance | use what exists, encrypted | NAS failure domain | IT | Yes | Phase 0 |
| Approval thresholds (60K/200K, chains) | **matrix as §12 sample** | business-defined | placeholders **[TBC]** | wrong routing until confirmed | Niren/Finance/TAL | Yes — **mandatory** | Phase 0 |
| AMC golden template | **provide sample (D3)** | defer AMC | AMC builder blocked without it | AMC slips to later phase | Niren | Yes | Phase 0 |
| Production model selection | **§26 benchmark decides** | pre-commit | evidence over preference | benchmark effort | Architect | Yes | Phase 2 |

## 32. Final Recommended Technology Stack

| Layer | Choice |
|---|---|
| App/API | Python 3.12, FastAPI (OpenAPI), server-rendered Jinja UI |
| Orchestration | LangGraph (+ Postgres checkpointer) |
| DB | PostgreSQL 16 + pgvector (+ pgcrypto, RLS) |
| AI runtime | Ollama; qwen3:14b + gemma3:4b (benchmark-gated); bge-m3 embeddings |
| Document path | existing proposal builder as service on Windows Server 2022 + licensed MS Office (COM), FastAPI wrapper, watchdog |
| File storage | NAS-backed immutable store, content-addressed |
| Auth | AD/LDAP if present, else local Argon2 + TOTP (admin) |
| AV/file security | ClamAV + YARA + oletools pipeline |
| Observability | Prometheus, Grafana, Loki, node/DCGM exporters; Wazuh (phase 3) |
| Backup | pg_basebackup + WAL PITR, NAS encrypted, offline media rotation |
| Deployment | Docker Compose on VM-1; Windows service + watchdog on VM-2 |

## 33. Production Acceptance Criteria

1. Zero unauthorised external sending (code inspection + attempted-send test: no code path exists).
2. Every state transition audited and chain-verified daily.
3. Every proposal linked to an approved opportunity and a valid registered template version.
4. Deal registration enforced: no `READY_FOR_PROPOSAL` without `Approved` (test: gate bypass attempt fails).
5. Quote totals independently validated; injected arithmetic error detected 100%.
6. Approval routing enforced per matrix; maker-checker verified.
7. No unapproved knowledge content retrievable in drafting context (SQL-filter test).
8. Generated DOCX passes structural validation; generated PDF passes visual review vs golden structure.
9. Workflow resumes after mid-node service restart (kill test) with zero duplicate effects.
10. Duplicate actions/events rejected (hash tests).
11. Access restrictions verified (secure-entity, finance fields, customer scoping; RLS tests).
12. Malware pipeline verified (EICAR + macro-laden samples quarantined).
13. Backup restoration tested to isolated VM; audit chain verified post-restore.
14. §26 model thresholds passed on the eval dataset.
15. Prompt-injection suite: 100% pass.
16. Pilot completed with no open critical defects; Niren format sign-off recorded.

## 34. Self-Critique

- **v1.0 vs v2.0 honestly:** v1.0's business understanding, workflow skeleton, human-gate model, golden-format path and audit ambition remain valid. Its platform choices (SQLite, ad-hoc state, single hard-coded threshold, thin RAG, thin security) were prototype-grade. v2.0 keeps the skeleton and replaces the chassis. The **prototype code is reused selectively**: extraction/RFQ/deal-reg/costing services carry over behind the new service interfaces and PostgreSQL; the UI is reworked onto the API layer; the COM golden-build proof becomes the doc-worker core.
- **LangGraph is mandated-preferred but not risk-free:** it's young; checkpoint/HITL APIs shift. Contingency: the design keeps authoritative state in PostgreSQL precisely so a swap to a custom state machine would cost the orchestration layer only, not the platform.
- **The modular monolith of 28 services is disciplined, not free:** boundaries must be enforced in code review or it degrades into a tangled app — the API contracts are the enforcement tool.
- **Unattended Office COM remains the least defensible component** — accepted because format fidelity is non-negotiable and proven; the quarantine + visual-regression harness exists precisely because this component *will* fail occasionally.
- **Benchmarks are planned, not yet run:** qwen3:14b/gemma3:4b are *candidates*, not confirmed. If they fail thresholds, the fallback set (larger Qwen on tighter quantization, Mistral-class, or a second GPU) is identified but unproven.
- **The approval matrix, AMC template, retention and secure-entity rules are placeholders by necessity** — architecture can absorb any answer, but Phase 0 must not slip these.
- **Single-operator reality:** this blueprint assumes ~1 lead engineer; phases are honest about effort, but a two-person team would change sequencing, not shape.
- **What is MVP-only vs production-required:** MVP may ship with local auth, single VM-1 DB, no Wazuh, no visual regression, manual failover; production **requires** the hardened doc-worker, visual QA, restore-tested DR, eval gate, and §33 in full.
