param(
    [Parameter(Mandatory=$true)]
    [string]$Agent,

    [Parameter(Mandatory=$true)]
    [string]$Task,

    [string]$Completed = "Not specified",

    [string]$Remaining = "Not specified",

    [string]$NextAction = "Review repository state and continue from the next incomplete approved task.",

    [string]$TestCommand = "Not specified",

    [string]$TestResult = "Not specified",

    [string]$Blockers = "None reported"
)

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$Branch = git branch --show-current
$CommitFull = git rev-parse HEAD
$CommitShort = git rev-parse --short HEAD

$Status = @(git status --short)
$RecentCommits = @(git log -5 --oneline)

$StagedFiles = @(git diff --cached --name-only)
$UnstagedFiles = @(git diff --name-only)
$UntrackedFiles = @(git ls-files --others --exclude-standard)

$DiffSummary = @(git diff --stat)
$StagedDiffSummary = @(git diff --cached --stat)

function Format-Items {
    param([object[]]$Items)

    if (-not $Items -or $Items.Count -eq 0) {
        return "- None"
    }

    return (($Items | ForEach-Object { "- $_" }) -join "`n")
}

function Format-Block {
    param(
        [object[]]$Items,
        [string]$EmptyText
    )

    if (-not $Items -or $Items.Count -eq 0) {
        return $EmptyText
    }

    return ($Items -join "`n")
}

$WorkingTreeStatus = Format-Block $Status "Clean"
$RecentCommitText = Format-Block $RecentCommits "No commits found"
$DiffSummaryText = Format-Block $DiffSummary "No unstaged diff"
$StagedDiffSummaryText = Format-Block $StagedDiffSummary "No staged diff"

$Lines = @(
    "# AI Agent Handoff",
    "",
    "## Handoff Metadata",
    "",
    "**Time:** $Timestamp",
    "",
    "**Previous Agent:** $Agent",
    "",
    "**Current Task:** $Task",
    "",
    "**Branch:** $Branch",
    "",
    "**Current Commit:** $CommitShort",
    "",
    "**Full Commit:** $CommitFull",
    "",
    "## Work Completed",
    "",
    $Completed,
    "",
    "## Work Remaining",
    "",
    $Remaining,
    "",
    "## Exact Next Action",
    "",
    $NextAction,
    "",
    "## Tests",
    "",
    "**Command:**",
    "",
    $TestCommand,
    "",
    "**Result:**",
    "",
    $TestResult,
    "",
    "## Blockers / Risks",
    "",
    $Blockers,
    "",
    "## Working Tree",
    "",
    '```text',
    $WorkingTreeStatus,
    '```',
    "",
    "## Staged Files",
    "",
    (Format-Items $StagedFiles),
    "",
    "## Unstaged Files",
    "",
    (Format-Items $UnstagedFiles),
    "",
    "## Untracked Files",
    "",
    (Format-Items $UntrackedFiles),
    "",
    "## Unstaged Diff Summary",
    "",
    '```text',
    $DiffSummaryText,
    '```',
    "",
    "## Staged Diff Summary",
    "",
    '```text',
    $StagedDiffSummaryText,
    '```',
    "",
    "## Latest Commits",
    "",
    '```text',
    $RecentCommitText,
    '```',
    "",
    "## Mandatory Startup for Next Agent",
    "",
    "Before modifying any code:",
    "",
    "1. Run:",
    "",
    "   git status",
    "   git branch --show-current",
    "   git log -5 --oneline",
    "",
    "2. Read:",
    "",
    "   - AGENTS.md",
    "   - CURRENT-STATE.md",
    "   - HANDOFF.md",
    "   - BACKLOG.md",
    "   - RUNBOOK.md",
    "   - BUILD-LOG.md",
    "   - AGENT-STATUS.md",
    "",
    "3. Verify:",
    "   - current branch",
    "   - current commit",
    "   - working tree state",
    "   - completed work",
    "   - remaining work",
    "   - required tests",
    "   - blockers",
    "",
    "4. Do not overwrite uncommitted work.",
    "",
    "5. Do not redo completed work unless validation proves it is required.",
    "",
    "6. Continue only from verified repository evidence.",
    "",
    "## Failover Rule",
    "",
    "If the next agent also reaches a usage or context limit:",
    "",
    "- stop at the smallest safe boundary",
    "- run relevant tests",
    "- update this handoff",
    "- record incomplete work precisely",
    "- commit completed work where appropriate",
    "- push to the configured remote",
    "- allow the next agent to continue from repository state"
)

$Lines -join "`r`n" | Set-Content "HANDOFF.md" -Encoding UTF8

Write-Host ""
Write-Host "=========================================="
Write-Host " AGENT HANDOFF UPDATED"
Write-Host "=========================================="
Write-Host ""
Write-Host "Agent:  $Agent"
Write-Host "Task:   $Task"
Write-Host "Branch: $Branch"
Write-Host "Commit: $CommitShort"
Write-Host "Time:   $Timestamp"
Write-Host ""
Write-Host "Working Tree:"
git status --short
Write-Host ""
Write-Host "HANDOFF.md updated successfully."
