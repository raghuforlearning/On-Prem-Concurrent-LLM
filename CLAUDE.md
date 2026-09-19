# Claude Code Project Instructions

This repository is shared between multiple AI coding agents.

Git is the source of truth.

Before making ANY code change:

1. Run:

   git status
   git branch --show-current
   git log -5 --oneline

2. Read these files in this order:

   - AGENTS.md
   - CURRENT-STATE.md
   - HANDOFF.md
   - BACKLOG.md
   - RUNBOOK.md
   - AGENT-STATUS.md

3. Determine:
   - current branch
   - last completed task
   - work in progress
   - next approved task
   - known failures
   - tests required

4. Do not overwrite uncommitted work created by another agent.

5. Do not change branches unless the task explicitly requires it.

6. Work in small atomic units.

7. Before stopping because of usage limits, context limits, or user request:

   - finish the smallest safe unit possible
   - run relevant tests
   - run git status
   - update HANDOFF.md
   - update CURRENT-STATE.md if project state changed
   - clearly record unfinished work

8. Never claim a task is complete unless validation/tests actually passed.

## Multi-Agent Environment

Primary agent:
Claude Code

Secondary agent:
OpenAI Codex

Fallback agent:
Other approved coding agent

Agents do not own the project.

The repository owns the project state.

