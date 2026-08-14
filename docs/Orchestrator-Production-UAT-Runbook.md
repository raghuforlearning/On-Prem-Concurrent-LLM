# NationLabs AI Presales Orchestrator — Production UAT Runbook

## Scope

This runbook prepares the active Orchestrator implementation for internal UAT on
the production server. It does not move the system to business-live by itself.

Active implementation:

- `build/p1-25/app`
- Docker Compose project: `nl-orchestrator`
- API/UI container: `nl-api`
- RAG worker: one `rag-worker` service

Frozen external systems remain outside this runbook:

- NationLabs Local LLM Platform
- NationLabs Proposal Builder

The Orchestrator may call those systems only through configured URLs and service
credentials.

## Target topology

Recommended UAT target:

- Orchestrator host: `192.168.71.2`
- Orchestrator UI/API: `http://192.168.71.2:8080/ui`
- PostgreSQL: reachable by the Orchestrator container on port `5432`
- Ollama/Local LLM: approved internal endpoint, currently expected as
  `http://192.168.71.11:11434` if it remains on the AI inference VM
- Proposal Builder: configured only through the frozen adapter contract

If PostgreSQL runs directly on the Docker host, set `PG_HOST=host.docker.internal`
inside `build/p1-25/app/.env`. If PostgreSQL is reached through the server IP,
set `PG_HOST=192.168.71.2`.

## Required `.env` values

Create `build/p1-25/app/.env` on the production server. This file is ignored and
must not be committed.

```text
PG_HOST=host.docker.internal
PG_PORT=5432
PG_DATABASE=orchestrator
PG_APP_PASSWORD=<real orchestrator_app password>

ORCHESTRATOR_HTTP_PORT=8080

OLLAMA_URL=http://192.168.71.11:11434
EMBEDDING_MODEL=bge-m3
RAG_DRAFT_MODEL=qwen3:14b
RAG_OLLAMA_TIMEOUT_S=300
RAG_WORKER_POLL_S=2

PROPOSAL_BUILDER_URL=<approved internal Proposal Builder URL>
PROPOSAL_BUILDER_BUILD_URL=
PROPOSAL_BUILDER_USERNAME=<approved service account>
PROPOSAL_BUILDER_PASSWORD=<approved service-account password>
PROPOSAL_BUILDER_TIMEOUT_S=120

QUOTE_VALIDATION_MONEY_TOLERANCE=0.01
QUOTE_VALIDATION_REQUIRE_CURRENCY_DETECTED=true
QUOTE_VALIDATION_REQUIRE_STATED_TOTALS=false
QUOTE_VALIDATION_REQUIRE_VAT=false
QUOTE_VALIDATION_REQUIRED_TERMS=
```

Set `PROPOSAL_BUILDER_BUILD_URL` only after the frozen Builder exposes the
documented `/api/v1/builds` contract.

## Pre-deployment checks

Run from the production server before starting the Orchestrator:

```bash
docker --version
docker compose version
docker ps
```

Confirm PostgreSQL connectivity from the server:

```bash
psql "postgresql://orchestrator_app:<password>@<pg-host>:5432/orchestrator" -c "select version();"
psql "postgresql://orchestrator_app:<password>@<pg-host>:5432/orchestrator" -c "select extname from pg_extension where extname='vector';"
```

Confirm Ollama model availability:

```bash
curl http://192.168.71.11:11434/api/tags
```

Required models:

- `bge-m3`
- `qwen3:14b`

## Start UAT stack

Run from `build/p1-25/app`:

```bash
docker compose --env-file .env up -d --build
docker compose ps
```

Open:

```text
http://192.168.71.2:8080/ui
```

Health check:

```bash
curl http://192.168.71.2:8080/healthz
```

The API should report PostgreSQL as healthy. Ollama should report healthy when
the `OLLAMA_URL` endpoint is reachable from the Orchestrator container.

## UAT smoke tests

Minimum smoke test sequence:

1. Create an opportunity.
2. Upload or paste a sample RFP.
3. Confirm extraction/classification result reaches human review.
4. Approve or answer clarification as applicable.
5. Generate an RFQ draft.
6. Approve disclosure if required.
7. Mark RFQ as sent; do not expect the Orchestrator to send email.
8. Upload/paste a sample vendor quote.
9. Validate quote totals and readiness status.
10. If multiple quotes exist, run comparison and record human selection.
11. Assemble proposal payload only after required gates pass.
12. Do not expect live CP/TP build completion until the frozen Proposal Builder
    `/api/v1/builds` endpoint is available.
13. Record a restore verification evidence event after backup/restore testing.

## Production-live gates

Do not promote from UAT to business-live until all gates below are satisfied:

- P1-14 historical dataset is available and schema-complete.
- P1-24 model go/no-go has passed using the P1-23 benchmark harness.
- Frozen Proposal Builder build endpoint is available for CP/TP output, or the
  business explicitly accepts recorded-artifact release flow limitations.
- Backup/PITR and isolated restore drill are completed and recorded.
- File security operations are installed and validated on the target servers
  where required, including ClamAV/Wazuh if they are part of the approved ops
  baseline.
- No production secrets are committed or exposed in logs/build artifacts.
- UAT owner signs off the complete RFQ → quote → validation → comparison →
  proposal/release lineage.

## Rollback

For an application-only rollback:

```bash
docker compose down
```

Then redeploy the prior validated app snapshot/commit. Do not run destructive
database reset commands against production workflow data.

For data rollback, use the approved PostgreSQL PITR/restore process and record
the restore verification through:

```text
POST /security/restore-verifications
```
