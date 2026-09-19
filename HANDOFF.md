# AI Agent Handoff

## Active Agent
Not assigned

## Current Task
Not assigned

## Current Branch
Run: git branch --show-current

## Last Known Good Commit
Run: git rev-parse HEAD

## Work Completed
- None recorded yet

## Work In Progress
- None

## Next Action
- Read AGENTS.md
- Read CURRENT-STATE.md
- Read BACKLOG.md
- Check Git status
- Continue only from verified repository state

## Files Changed
- None

## Tests Run
- None

## Test Result
- Not tested

## Known Issues / Risks
- None recorded

## Important Decisions
- Git repository is the project source of truth.
- Claude Code, Codex, and other coding agents must work against the same local repository.
- Agents must not overwrite another agent's uncommitted work.
- Before handoff, update this file and CURRENT-STATE.md.

## Handoff Procedure
1. Finish the smallest safe unit of work.
2. Run relevant tests.
3. Run git status.
4. Update HANDOFF.md.
5. Update CURRENT-STATE.md if project state changed.
6. Commit changes.
7. Push when appropriate.
8. Next agent pulls/checks branch before continuing.

