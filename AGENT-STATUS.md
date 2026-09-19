# Agent Runtime Status

## Project
AI Presales Orchestrator

## Repository
C:\Raghu Official\AI works\Kimi\Research & Brainstorming\repo_sync_personal

## Source of Truth
Local Git repository + configured GitHub remote

## Preferred Agent Order
1. Claude Code
2. OpenAI Codex
3. Third fallback agent

## Current Active Agent
UNASSIGNED

## Current Session
UNASSIGNED

## Current Branch
codex/p1-25-security-hardening

## Current Commit
aaa56fdc7e502ed438f317d34b7e4467c65dae9e

## Working Tree
?? .agent-backup/ ?? HANDOFF.md

## Failover Rule
If the active agent reaches a usage limit or must stop:

1. Do not begin a new major task.
2. Finish or revert the current atomic change.
3. Run tests.
4. Update HANDOFF.md.
5. Commit completed work.
6. Record remaining work.
7. Stop.
8. Next agent reads project state before making changes.

## Mandatory Startup Sequence
Every coding agent must first run:

git status
git branch --show-current
git log -5 --oneline

Then read:

- AGENTS.md
- CURRENT-STATE.md
- HANDOFF.md
- BACKLOG.md
- RUNBOOK.md

No coding should start before those checks are complete.

