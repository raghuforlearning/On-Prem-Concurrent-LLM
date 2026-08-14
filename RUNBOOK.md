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
- a `FAILED_REVIEW` draft job requires human inspection; never silently
  publish its output.

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
- configure `PROPOSAL_BUILDER_BUILD_URL` only when the frozen Builder exposes
  the documented `/api/v1/builds` contract. If unset, the Orchestrator falls
  back to `PROPOSAL_BUILDER_URL`.
- `POST /proposals/{type}/assemble` must have an active accepted quote,
  current deterministic quote validation, approved `PROPOSAL_VALUE` approval
  and a satisfied Deal Registration gate.
- `POST /proposals/{id}/build` submits the frozen payload hash to Builder and
  records the returned Builder job reference. A failed submission can be retried
  without changing the frozen payload.
- `POST /proposal-build-jobs/{id}/refresh` records returned artifact refs and
  SHA-256 hashes. Missing artifact hashes quarantine the job for human review.
- live CP completion is blocked until the external Builder endpoint is
  available; the passed implementation validates the Orchestrator foundation
  with the documented adapter contract.

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

**External-input gated**

All currently actionable Orchestrator P1 implementation items are complete
through P1-25. Remaining blocked/deferred work requires external inputs:
P1-20/P1-21 need frozen Proposal Builder build output, and P1-24 needs the real
P1-14 labelled historical dataset benchmark run. Production security operations
such as ClamAV/Wazuh/full isolated restore drills must be validated on the target
servers before production sign-off.

The current UAT stays local in Docker. The 14-Aug-2026 Hyper-V assessment found
4.1 GB available RAM, which is insufficient for the recommended dedicated
Orchestrator VM. Do not place the Orchestrator inside the frozen AI Inference or
Proposal Builder VMs. Reassess capacity when the system is production-ready.

For the later dedicated-server deployment, use:

```text
docs/Orchestrator-Production-UAT-Runbook.md
```

The UAT deployment may run on the production server before business-live, but it
must remain clearly marked as UAT until the live gates in that runbook are met.
