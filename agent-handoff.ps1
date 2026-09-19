param(
    [Parameter(Mandatory=$true)]
    [string]$Agent,

    [Parameter(Mandatory=$true)]
    [string]$Task,

    [string]$NextAction = "Review HANDOFF.md and continue from verified repository state."
)

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

$Branch = git branch --show-current
$Commit = git rev-parse --short HEAD
$Status = git status --short
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

if ([string]::IsNullOrWhiteSpace($Status)) {
    $StatusText = "Clean"
}
else {
    $StatusText = $Status
}

@"
# AI Agent Handoff

## Handoff Time
$Timestamp

## Previous Agent
$Agent

## Current Task
$Task

## Current Branch
$Branch

## Last Known Commit
$Commit

## Working Tree
$StatusText

## Next Action
$NextAction

## Mandatory Startup for Next Agent

Run:

git status
git branch --show-current
git log -5 --oneline

Then read:

1. AGENTS.md
2. CURRENT-STATE.md
3. HANDOFF.md
4. BACKLOG.md
5. RUNBOOK.md
6. AGENT-STATUS.md

## Safety Rule

Do not overwrite uncommitted work.

If the working tree is not clean, inspect the changes before continuing.

"@ | Set-Content "HANDOFF.md" -Encoding UTF8

Write-Host ""
Write-Host "Handoff updated."
Write-Host "Agent: $Agent"
Write-Host "Branch: $Branch"
Write-Host "Commit: $Commit"
Write-Host ""
Write-Host "Next agent can now take over."
