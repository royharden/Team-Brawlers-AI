# precommit_changed_files.ps1 — Windows PowerShell twin of
# precommit_changed_files.sh. Same purpose: run the pre-commit hooks an agent
# is about to push BEFORE pushing, to catch cheap CI failures locally.
#
# Adapted from EMR-SO/openemr/scripts/precommit_changed_files.sh.
#
# Usage (from Team-Brawlers-AI repo root):
#   .\scripts\precommit_changed_files.ps1                # staged + modified
#   .\scripts\precommit_changed_files.ps1 -StagedOnly    # only `git add`-ed
#   .\scripts\precommit_changed_files.ps1 -AllFiles      # every file
#   .\scripts\precommit_changed_files.ps1 -SkipMypy      # skip slowest hook
#
# Exit codes:
#   0 = clean (or no files matched).
#   1 = at least one hook reported a violation.
#   2 = pre-commit not installed / misconfigured.
#
# Why a PowerShell twin: Windows hosts running native PowerShell (no
# Git-Bash) need a script that doesn't depend on bash/awk/xargs. The
# OneDrive path quoting trap (paths with spaces) bites both shells
# differently — handle it once here, once in the .sh.

[CmdletBinding()]
param(
    [switch]$StagedOnly,
    [switch]$AllFiles,
    [switch]$SkipMypy
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Pre-flight: confirm pre-commit is on PATH.
# ---------------------------------------------------------------------------
if (-not (Get-Command pre-commit -ErrorAction SilentlyContinue)) {
    Write-Error @"
pre-commit is not on PATH.

Install (one-time per machine):
  pip install --user pre-commit
  # OR via poetry:
  poetry add --group dev pre-commit

Then optionally install the git hook so commits get checked automatically:
  pre-commit install
  pre-commit install --hook-type pre-push

Until then, this script is the manual fallback.
"@
    exit 2
}

# ---------------------------------------------------------------------------
# Resolve repo root, cd there. Script lives in <repo>/scripts/.
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $PSCommandPath
$RepoRoot  = Split-Path -Parent $ScriptDir
Push-Location $RepoRoot
try {
    # Mode determination — flags are mutually exclusive.
    if ($AllFiles -and $StagedOnly) {
        Write-Error "Cannot pass both -AllFiles and -StagedOnly."
        exit 2
    }

    # Environment for SKIP env-var trick (pre-commit honours $env:SKIP).
    if ($SkipMypy) { $env:SKIP = 'mypy' }

    # -----------------------------------------------------------------------
    # All-files mode — defer to pre-commit's own runner.
    # -----------------------------------------------------------------------
    if ($AllFiles) {
        Write-Host ">>> mode=all-files (running pre-commit run --all-files)"
        & pre-commit run --all-files
        exit $LASTEXITCODE
    }

    # -----------------------------------------------------------------------
    # Build the file list. Always trim CR; PowerShell preserves them when
    # piping native git output, which breaks downstream string ops.
    # -----------------------------------------------------------------------
    function Get-GitFileList {
        param([string]$Mode)

        if ($Mode -eq 'staged') {
            $raw = git diff --cached --name-only --diff-filter=ACMR
        } else {
            $staged   = git diff --cached --name-only --diff-filter=ACMR
            $modified = git diff --name-only --diff-filter=ACMR
            $raw      = @($staged) + @($modified)
        }
        return $raw |
            Where-Object { $_ -and ($_.Trim() -ne '') } |
            ForEach-Object { $_.TrimEnd("`r") } |
            Sort-Object -Unique
    }

    $modeName = if ($StagedOnly) { 'staged' } else { 'changed' }
    $files = Get-GitFileList -Mode $modeName

    if (-not $files -or $files.Count -eq 0) {
        Write-Host ">>> no changed/staged files. nothing to check."
        exit 0
    }

    # Filter to files that still exist on disk (covers delete + rename).
    $existing = $files | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }

    if (-not $existing -or $existing.Count -eq 0) {
        Write-Host ">>> all changed files were deleted; nothing to check."
        exit 0
    }

    Write-Host ">>> checking the following files (mode=$modeName):"
    $existing | ForEach-Object { Write-Host "    $_" }

    # -----------------------------------------------------------------------
    # Invoke pre-commit. The call operator (&) handles array splatting
    # safely — every element becomes one argv slot, so paths with spaces
    # survive intact (OneDrive paths like "C:\Users\Roy Harden\..." bit
    # us repeatedly in EMR-SO's lessons file).
    # -----------------------------------------------------------------------
    & pre-commit run --files @existing
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    if ($SkipMypy) { Remove-Item Env:SKIP -ErrorAction SilentlyContinue }
}
