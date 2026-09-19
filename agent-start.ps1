param(
    [string]$Agent = "Unknown"
)

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

Write-Host ""
Write-Host "=========================================="
Write-Host " AI PRESALES ORCHESTRATOR - AGENT START"
Write-Host "=========================================="
Write-Host ""

Write-Host "Agent: $Agent"
Write-Host "Repository: $Repo"

Write-Host ""
Write-Host "Current Branch:"
git branch --show-current

Write-Host ""
Write-Host "Current Commit:"
git rev-parse --short HEAD

Write-Host ""
Write-Host "Working Tree:"
git status --short

Write-Host ""
Write-Host "Latest Commits:"
git log -5 --oneline

Write-Host ""
Write-Host "Required project context:"
Write-Host "  AGENTS.md"
Write-Host "  CURRENT-STATE.md"
Write-Host "  HANDOFF.md"
Write-Host "  BACKLOG.md"
Write-Host "  RUNBOOK.md"
Write-Host "  AGENT-STATUS.md"

Write-Host ""
Write-Host "----- CURRENT HANDOFF -----"
Get-Content HANDOFF.md -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=========================================="
Write-Host "Read project files before modifying code."
Write-Host "=========================================="
