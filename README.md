# NationLabs AI Presales Orchestrator

## Purpose

This repository is the working implementation repository for the **NationLabs AI Presales Orchestrator**.

The Orchestrator manages the presales workflow from opportunity/RFP intake through AI analysis, vendor/RFQ coordination, Deal Registration, quote lifecycle, approvals, proposal handoff and follow-up.

It is designed for local / air-gapped deployment.

## System boundaries

The solution consists of three separate systems:

### 1. AI Presales Orchestrator — active development
Responsibilities include:
- opportunities and RFP intake,
- workflow orchestration,
- LangGraph state/checkpoint management,
- vendor and RFQ workflow,
- Deal Registration,
- follow-up,
- quote lifecycle,
- approvals,
- RAG,
- audit,
- dashboards/review UI,
- Proposal Builder handoff.

### 2. NationLabs Local LLM Platform — frozen external system
Provides local AI inference through Ollama/approved local models and existing guardrail capability.

The Orchestrator consumes this through an adapter.

### 3. NationLabs Proposal Builder — frozen external system
Provides deterministic proposal/document-domain capabilities already implemented by NationLabs.

The Orchestrator consumes this through an adapter.

**The Local LLM does not directly control the Proposal Builder. The Orchestrator is the only coordinator.**

## Active Orchestrator technology

- FastAPI
- LangGraph
- PostgreSQL 16
- pgvector
- SQLAlchemy
- Docker / Docker Compose
- local Ollama inference via adapter
- lightweight browser review UI

## Current validated milestone

**P1-13 PASSED**

Known-good reference commit:

`3a0488a` — `P1-13 PASSED: review board UI + file intake with OCR provenance`

See:
- `AGENTS.md`
- `CURRENT-STATE.md`
- `BACKLOG.md`
- `build/BUILD-LOG.md`
- `docs/NationLabs-Orchestrator-Architecture-v2.0.md`
- `docs/NationLabs-Orchestrator-Phase0-Discovery-Gap-Assessment.md`

## Important repository note

This repository contains historical Local LLM and legacy Orchestrator material.

Examples:
- `serving/`
- `infra/`
- `nationlabs-orchestrator/` legacy Flask/SQLite prototype
- older `build/p1-*` snapshots

Do not infer the active architecture from those folders alone.

For implementation decisions, follow `AGENTS.md` and `CURRENT-STATE.md`.

## Current development direction

Architecture and Phase 0 are frozen as the implementation baseline unless a genuine implementation blocker is found.

Active work continues in:

**P1-C — Quote Intelligence + RAG**

The Local LLM Platform and Proposal Builder must not be modified as part of Orchestrator development.

## Working discipline

Every implementation task must follow:

**BUILD -> TEST -> PASS -> DOCUMENT -> COMMIT -> NEXT**

A task is not complete until:
- acceptance tests pass,
- regression tests pass,
- build log/current state/backlog are updated,
- changes are committed with the relevant P1 task ID.

## Air-gap rule

Production design must remain compatible with an air-gapped environment.

Do not add unapproved cloud AI, SaaS APIs or internet dependencies to the Orchestrator.
