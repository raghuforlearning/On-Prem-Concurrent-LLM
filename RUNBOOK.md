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

**P1-13 PASSED**

Known-good reference commit:

`3a0488a`

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

**P1-15 — Quote lifecycle / Proposal Builder adapter**

P1-14 historical dataset collection can proceed in parallel as an owner/data activity.

Do not modify the Proposal Builder itself.
