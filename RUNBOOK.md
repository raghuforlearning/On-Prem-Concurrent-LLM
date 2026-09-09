# RUNBOOK.md — Repository Operations and Codex Handoff

## Purpose

This file is the **current repository-level operational runbook for Orchestrator development**.

Historical Local LLM build details that previously occupied the root runbook are legacy infrastructure material. Preserve that history separately if needed, but do not use it as the active Orchestrator implementation plan.

For current implementation decisions, use:

1. `AGENTS.md`
2. `CURRENT-STATE.md`
3. `BACKLOG.md`
4. `docs/NationLabs-Orchestrator-Architecture-v2.0.md`
5. `docs/NationLabs-Orchestrator-Phase0-Discovery-Gap-Assessment.md`
6. `build/BUILD-LOG.md`

## 1. Development baseline

Known-good milestone:

**P1-25 PASSED**

Active implementation:

`build/p1-25/app/`

Do not reset the repository to this commit automatically because the working tree contains uncommitted historical changes.

Before every development session:

```bash
git status
git log --oneline -10
```

Identify:
- current branch,
- uncommitted files,
- active implementation folder,
- previous task status.

## 2. Active code rule

The latest validated P1 implementation is the active baseline.

Do not resume implementation from the old Flask/SQLite prototype simply because it lives under `nationlabs-orchestrator/`.

Inspect `build/BUILD-LOG.md` and the latest validated P1 application first.

## 3. Frozen systems

Do not modify as part of Orchestrator work:

- Local LLM runtime / Ollama / Guardrails stack
- NationLabs Proposal Builder

All integration logic belongs in Orchestrator adapters.

## 4. Safe branching

Recommended pattern:

```bash
git checkout main
git pull
git checkout -b build/p1-15-proposal-builder-adapter
```

Use one branch per meaningful P1 task.

Do not mix unrelated legacy Local LLM/Guardrails changes into Orchestrator feature commits.

## 5. Pre-task checklist

Before coding:

- read `AGENTS.md`
- read `CURRENT-STATE.md`
- read relevant `BACKLOG.md` item
- inspect latest implementation
- run relevant baseline tests
- inspect DB migration/state requirements
- verify no secret is being committed

## 6. Task completion checklist

A task is complete only when:

- implementation exists,
- acceptance test passes,
- affected regression tests pass,
- `build/BUILD-LOG.md` updated,
- `CURRENT-STATE.md` updated,
- `BACKLOG.md` updated,
- this runbook updated if operational steps changed,
- Git commit created with P1 task ID,
- commit SHA reported.

## 7. Commit format

Examples:

```text
P1-15: add frozen Proposal Builder adapter and quote lifecycle persistence
P1-16: add deterministic quote readiness validation
P1-17: implement approved-content pgvector RAG
P1-18: add multi-vendor quote revision comparison
```

## 8. External communication

No email application is connected yet.

Current process:
- Orchestrator drafts RFQ/follow-up.
- Human sends through an approved external channel.
- User records `Mark as Sent` / follow-up details.
- Vendor response is pasted/uploaded.
- Quote receipt stops the relevant quote follow-up.

Do not add SMTP or Microsoft 365 integration unless it becomes an approved backlog item.

## 9. Deal Registration

Deal Registration is enforced when required.

Allowed before DR approval:
- quote receipt,
- quote validation,
- comparison,
- costing preparation,
- clarifications.

Block proposal generation/release until the required DR state is acceptable.

Do not assume DR is required for every vendor.

## 10. LLM concurrency

Use queued asynchronous processing.

MVP guidance:
- maximum 1–2 heavy Qwen jobs concurrently,
- additional RFPs remain queued,
- CPU/file tasks can run in parallel,
- Proposal Builder processing is independent from GPU inference.

## 11. Secrets

Never commit:
- passwords,
- API keys,
- tokens,
- private keys,
- real production credentials.

Use `.env.example` for placeholders only.

For the active P1-18 application, create an ignored `build/p1-18/app/.env` with:

```text
PG_APP_PASSWORD=<existing orchestrator_app database password>
PROPOSAL_BUILDER_URL=<approved internal Builder URL>
PROPOSAL_BUILDER_USERNAME=<approved service account>
PROPOSAL_BUILDER_PASSWORD=<approved service-account password>
PROPOSAL_BUILDER_TIMEOUT_S=120
QUOTE_VALIDATION_MONEY_TOLERANCE=0.01
QUOTE_VALIDATION_REQUIRE_CURRENCY_DETECTED=true
QUOTE_VALIDATION_REQUIRE_STATED_TOTALS=false
QUOTE_VALIDATION_REQUIRE_VAT=false
QUOTE_VALIDATION_REQUIRED_TERMS=
EMBEDDING_MODEL=bge-m3
RAG_DRAFT_MODEL=qwen3:14b
RAG_OLLAMA_TIMEOUT_S=300
RAG_WORKER_POLL_S=2
```

The P1-18 `.dockerignore` excludes `.env` and `.env.*` from the Docker build
context. Before distributing an image, verify `/srv/app/.env` does not exist in
the image. Do not publish expanded Compose configuration because it may print
environment-provided credentials.

Quote-validation policy is server-controlled. `QUOTE_VALIDATION_REQUIRED_TERMS`
is a comma-separated subset of `validity,payment,delivery`. Enable stated-total
or VAT requirements only after the applicable commercial policy is approved;
do not hard-code or ask an LLM to infer a tax rule.

The `quote-archive` Docker volume stores immutable raw quote sources. Preserve
and back it up together with PostgreSQL workflow data; the database retains each
archive path and SHA-256 digest.

P1-17 operations:
- the approved interim host is the `aiinference` VM at `192.168.71.11`; the
  physical Hyper-V host is `192.168.71.2`.
- Ollama must expose `bge-m3` with 1,024-dimensional embeddings and
  `qwen3:14b` through the internal adapter endpoint.
- knowledge ingestion always creates `DRAFT`; an authorized reviewer must
  approve cleared content before customer-facing retrieval.
- `FLAGGED`, expired, superseded, unapproved or out-of-scope content must not
  be manually promoted through direct database edits.
- run exactly one `rag-worker` service for the MVP.
- grounded `qwen3:14b` calls disable thinking for schema-constrained output.
  Malformed output receives exactly one stricter local retry; a second invalid
  response fails closed. Do not strip wrappers, repair partial JSON manually or
  bypass citation validation.
- a `FAILED_REVIEW` draft job requires human inspection; never silently
  publish its output. Preserve failed jobs as audit history and create a new
  job only after the underlying content, connectivity or contract issue is
  resolved.

P1-18 operations:
- record a non-AED exchange rate with the actual rate date and an internal
  finance/source reference before comparison. The Orchestrator does not fetch
  rates from the internet and no LLM may infer one.
- retain all quote revisions. Only a current, parsed, deterministically
  validated quote can enter a new comparison or be selected.
- compare quotes while Deal Registration is pending when business work needs to
  continue, but treat `proposal_eligible=false` as a hard downstream release
  gate until that vendor path is `APPROVED` or `NOT_REQUIRED`.
- do not edit comparison run result JSON or a selection snapshot in-place;
  create a new comparison/selection decision with its own audit history.

P1-19 operations:
- proposal handoff is Orchestrator-only; do not modify or copy the Proposal
  Builder implementation.
- set `PROPOSAL_BUILDER_BUILD_TRANSPORT=existing_sync` for the currently
  validated frozen Builder. It uses `/api/generate` for CP/AMC and
  `/api/generate-tp-vendor` for TP. Keep `v1_async` only for a future Builder
  service that implements the documented `/api/v1/builds` job contract.
- configure `PROPOSAL_BUILDER_URL`, service credentials,
  `PROPOSAL_BUILDER_ARTIFACT_ROOT` and
  `PROPOSAL_BUILDER_SOURCE_ARTIFACT_ROOTS` through the ignored `.env` file.
  Never commit the credentials.
- TP requires `context.proposal_builder.vendor_tp_artifact` with a local
  `artifact_ref`, SHA-256 and optional filename. The adapter accepts only PDF or
  DOCX files inside the configured controlled roots, verifies size and hash,
  then uploads the file to the frozen Builder.
- TP also requires an explicit customer identity contract in the frozen
  Builder context: the masked `client_name` code, `client_real_name`,
  `client_aliases` and `mask_client=true`. The adapter maps these to the
  existing Builder multipart fields; do not place aliases in source control or
  logs.
- `POST /proposals/{type}/assemble` must have an active accepted quote,
  current deterministic quote validation, approved `PROPOSAL_VALUE` approval
  and a satisfied Deal Registration gate.
- `POST /proposals/{id}/build` submits the frozen payload hash to Builder and
  records the returned Builder job reference. A failed submission can be retried
  without changing the frozen payload.
- `POST /proposal-build-jobs/{id}/refresh` records returned artifact refs and
  SHA-256 hashes. Missing artifact hashes quarantine the job for human review.
- `GET /integrations/proposal-builder/build-health` must report `status=ok`,
  `build_transport=existing_sync`, `build_endpoint=/api/generate` and
  `tp_build_endpoint=/api/generate-tp-vendor` before live generation.
- the existing synchronous transport returns DOCX only. P1-22 release remains
  fail-closed until a final SHA-256-tracked PDF also exists.

P1-20 operations:
- TP requires `context.proposal_builder.customer_commercials`. This is a
  customer-facing selling-price snapshot, separate from the selected vendor
  quote. It must contain currency, line items, subtotal, VAT rate, VAT amount,
  grand total, payment/validity/delivery terms and an `authority` object.
- `authority.kind` must be `APPROVED_COSTING_SHEET`; source SHA-256,
  `approved_by` and `approved_at` are mandatory. Never place passwords or the
  costing workbook itself in the frozen JSON payload.
- only part number, description, quantity, unit price and line total are sent
  to the Builder. Internal cost, buy price, vendor cost, margin and markup
  fields are rejected.
- the adapter independently checks line arithmetic, subtotal, VAT and grand
  total with `Decimal`; no LLM participates in commercial arithmetic.
- TP also requires approved `rag_provenance` with draft/retrieval IDs,
  reviewer and review timestamp.
- generated TP output must pass `p1-20.tp-source-aware.v2`: valid DOCX, immediate
  `Proposed BOQ -> Commercials -> Acceptance` order, required BOQ/commercial
  tables, numerically exact frozen selling facts despite display commas, no
  internal commercial labels, approved RAG provenance, no surviving real-name
  client alias in any Word story, valid embedded-image relationships and source
  graphic preservation evidence. There is no global 16-shape minimum because
  genuine vendor documents contain different numbers of diagrams.
- any failed validation is persisted and changes the build/proposal state to
  `QUARANTINED`. Do not manually promote it or prepare a release package.
- structural success does not replace visual review. The 19-Aug synthetic live
  run incorrectly reused generated CP output as the TP source; it remains valid
  quarantine evidence but is not TP fidelity evidence.
- the corrected opt-in live test requires a genuine vendor PDF/DOCX staged in
  `/srv/data/rfp_archive` or `/srv/data/quote_archive`, plus its pinned SHA-256:
  `P119_TEST_VENDOR_TP_PATH` and `P119_TEST_VENDOR_TP_SHA256`. It deliberately
  rejects files under `PROPOSAL_BUILDER_ARTIFACT_ROOT`, so generated CP output
  cannot be recycled as a TP fixture.
- run the corrected test only after verifying Builder `/api/env` returns the
  expected environment. From `build/p1-25/app`, use the ignored `.env` and pass
  the live-test values only to the one-off test container:

  ```powershell
  docker compose --env-file .env run --rm --no-deps `
    -e P119_TEST_EXISTING_BUILDER_LIVE=1 `
    -e P119_TEST_VENDOR_TP_PATH=/srv/data/quote_archive/vendor-tp.pdf `
    -e P119_TEST_VENDOR_TP_SHA256=<verified-lowercase-sha256> `
    api python -m unittest tests.test_p119_existing_builder_live -v
  ```

- The 20-Aug result is historical evidence for the retired v1 shape-floor
  profile only. The 25-Aug reviewed Builder artifact still contained real
  client aliases because its generation fixture did not supply the masking
  contract. Regenerate through the Orchestrator with the required identity
  fields, then run v2 structural validation and page-by-page human visual
  review. Do not release the reviewed artifact.

P1-22 operations:
- proposal release is human-controlled. The Orchestrator records release
  package readiness and submission evidence; it does not send email or submit
  to external portals.
- prepare release only from a completed document build job with passing
  validation and final DOCX/PDF artifact refs plus SHA-256 hashes.
- record customer submission evidence with method, recipient, evidence ref,
  evidence SHA-256, submitted-by and recorded-by fields.
- repeated submission recording for the same release package is idempotent and
  returns the existing submission.

P1-23 operations:
- benchmark datasets are local JSON files; do not upload them to cloud services.
- use `POST /benchmarks/run` with a local dataset path to generate and persist
  the report.
- sample or partial datasets intentionally return `INSUFFICIENT_DATA`; do not
  use them for production model sign-off.
- P1-24 requires the real P1-14 labelled historical dataset before a go/no-go
  decision can be made.

P1-14 collection operations:
- from `build/p1-25/app`, run
  `python historical_dataset.py init --root .\local-historical-dataset --count 30`;
- keep real deal evidence and populated labels inside that ignored local folder;
- use `dataset_pack/README.md` and the copied `labels.xlsx` for second-person
  validation;
- run `python historical_dataset.py validate --root .\local-historical-dataset
  --report .\local-historical-dataset\completeness-report.json`;
- exit code `2` is expected until 30 complete validated deals pass; use
  `--allow-incomplete` only for progress reporting, never for P1-24 sign-off;
- do not commit or bake real customer/vendor artifacts into a Docker image.

P1-25 operations:
- use `POST /security/files/scan` for local file screening decisions before
  processing suspicious uploads.
- a `QUARANTINE` file decision or `FLAG` prompt-injection decision must be
  reviewed by an authorized human; do not manually promote flagged content.
- use `POST /security/rbac/check` for policy verification during integration
  work; role definitions live in the Orchestrator database and are seeded at
  startup.
- use `POST /security/restore-verifications` to record restore/audit-chain
  evidence from deployment or DR exercises.
- ClamAV/Wazuh/full isolated restore drills remain production operations work;
  do not claim they are running until installed and verified on the target
  servers.

If a credential appears in a build log or shared archive, rotate it before production use.

## 12. Codex takeover sequence

First Codex run must be an audit only.

Codex must:

1. Read the source-of-truth documents.
2. Inspect the repository.
3. Inspect Git status/history.
4. Run tests.
5. Compare code to documented status.
6. Report the next task.
7. Stop before code changes.

Only after review should Codex begin P1-C implementation.

## 13. Current next engineering priority

**P1-20 external acceptance remediation / conditional P1-21**

The Orchestrator P1 foundation is complete through P1-25. Remaining work is:
the P1-20 gate is implemented and a genuine-vendor-input live TP still failed
golden fidelity. A render worker cannot recreate missing proposal content or
embedded objects, so P1-21 is not the automatic remedy. The external frozen
Builder owner must first produce a DOCX that independently passes P1-20. P1-24
still needs the real P1-14 labelled historical dataset benchmark run.
Production security operations such as ClamAV/Wazuh/full isolated restore
drills must be validated on the target servers before production sign-off.

The current UAT stays local in Docker. The 14-Aug-2026 Hyper-V assessment found
4.1 GB available RAM, which is insufficient for the recommended dedicated
Orchestrator VM. Do not place the Orchestrator inside the frozen AI Inference or
Proposal Builder VMs. Reassess capacity when the system is production-ready.

P1-21 worker operations, only if a compliant Builder DOCX exists and automatic
PDF delivery is confirmed mandatory:
- the implementation and current WT matrix are in
  `docs/P1-21-Windows-Document-Worker-Feasibility.md`;
- never run the Office worker when an unmanaged `WINWORD.EXE` process already
  exists; investigate and clear the orphan first;
- accept only a Builder-produced DOCX whose SHA-256 matches an explicit
  `CLEARED` security record and whose path is under an allow-listed artifact
  root;
- run one Office job at a time; retry once; quarantine any timeout, hash
  mismatch, unexpected artifact or Office failure;
- a quarantined job is not releasable and must not be manually relabelled
  passed;
- do not deploy the worker as a service or run reboot tests until the two
  conditional entry gates above are met and IT approves the candidate Windows
  VM, licensed Office and low-privilege service account.

P1-21 code-side worker configuration (candidate VM only after approval):
- set `DOCUMENT_WORKER_TOKEN` to the same dedicated random value in the ignored
  Orchestrator `.env` and in the Windows service account environment; never use
  the Proposal Builder credential;
- set `DOCUMENT_RENDER_ARTIFACT_ROOT` only on the Orchestrator API host; the
  Compose default is `/srv/data/document_render_artifacts` in its own volume;
- set Windows `ORCHESTRATOR_URL`, `DOCUMENT_WORKER_INBOX_ROOT`,
  `DOCUMENT_WORKER_OUTPUT_ROOT` and optionally `DOCUMENT_WORKER_CA_BUNDLE`;
  all Windows filesystem paths must be absolute;
- install only the offline-mirrored dependency in
  `build/p1-25/app/windows-document-worker/requirements.txt`, then run
  `python windows-document-worker/worker_service.py --once` for a controlled
  smoke check before any service registration;
- do not copy Proposal Builder source/templates to the worker. The worker pulls
  only the hash-cleared Builder DOCX from the Orchestrator and returns rendered
  DOCX/PDF to Orchestrator-controlled storage.

For the later dedicated-server deployment, use:

```text
docs/Orchestrator-Production-UAT-Runbook.md
```

The UAT deployment may run on the production server before business-live, but it
must remain clearly marked as UAT until the live gates in that runbook are met.
