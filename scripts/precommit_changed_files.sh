#!/usr/bin/env bash
#
# precommit_changed_files.sh — run pre-commit hooks on the files an agent is
# about to commit, BEFORE pushing. Catches the cheap CI failures (whitespace,
# EOF, codespell, ruff, ruff-format, mypy) locally so CI doesn't reject the
# push after a multi-minute wait.
#
# Adapted from EMR-SO/openemr/scripts/precommit_changed_files.sh. Same
# rationale: every clone has to opt-in to pre-commit hooks via
# `pre-commit install`; until then this script is the manual fallback.
#
# Usage (from Team-Brawlers-AI repo root):
#   ./scripts/precommit_changed_files.sh                  # staged + modified
#   ./scripts/precommit_changed_files.sh --staged-only    # only `git add`-ed
#   ./scripts/precommit_changed_files.sh --all-files      # every file
#   ./scripts/precommit_changed_files.sh --skip-mypy      # skip slowest hook
#
# Exit codes:
#   0 = clean (or no files matched).
#   1 = at least one hook reported a violation. Re-run after fixing, or
#       re-stage auto-fixed files (`git add` then commit).
#   2 = pre-commit not installed / misconfigured.
#
# See agentdocs/agent_lessons.md "pre-commit is not auto-installed" + the
# `python-fix-discipline-team-brawlers-ai` skill for canonical fix patterns.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# Pre-flight: confirm pre-commit is installed.
# ---------------------------------------------------------------------------
if ! command -v pre-commit >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: pre-commit is not on PATH.

Install (one-time per machine):
  pip install --user pre-commit
  # OR via poetry (already a dev dep once you add it):
  poetry add --group dev pre-commit

Then optionally install the git hook so commits get checked automatically:
  pre-commit install
  pre-commit install --hook-type pre-push

Until then, this script is the manual fallback.
EOF
    exit 2
fi

# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------
mode="changed"
skip_mypy="no"
for arg in "$@"; do
    case "${arg}" in
        --staged-only) mode="staged" ;;
        --all-files)   mode="all"    ;;
        --skip-mypy)   skip_mypy="yes" ;;
        -h|--help)
            sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# //; s/^#//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: ${arg}" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# All-files mode: short-circuit through pre-commit's own runner.
# ---------------------------------------------------------------------------
if [[ "${mode}" == "all" ]]; then
    echo ">>> mode=all-files (running pre-commit run --all-files)"
    if [[ "${skip_mypy}" == "yes" ]]; then
        SKIP=mypy pre-commit run --all-files
    else
        pre-commit run --all-files
    fi
    exit $?
fi

# ---------------------------------------------------------------------------
# Build the file list.
# ---------------------------------------------------------------------------
case "${mode}" in
    staged)
        FILES=$(git diff --cached --name-only --diff-filter=ACMR)
        ;;
    changed)
        # staged + unstaged-but-modified, deduped
        FILES=$( (git diff --cached --name-only --diff-filter=ACMR; \
                  git diff --name-only --diff-filter=ACMR) | sort -u)
        ;;
    *)
        echo "ERROR: unknown mode: ${mode}" >&2
        exit 2
        ;;
esac

if [[ -z "${FILES}" ]]; then
    echo ">>> no changed/staged files. nothing to check."
    exit 0
fi

# Filter to files that actually still exist (covers deletes + renames).
EXISTING_FILES=""
while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    [[ -f "${f}" ]] || continue
    EXISTING_FILES+="${f}"$'\n'
done <<< "${FILES}"
EXISTING_FILES="${EXISTING_FILES%$'\n'}"

if [[ -z "${EXISTING_FILES}" ]]; then
    echo ">>> all changed files were deleted; nothing to check."
    exit 0
fi

echo ">>> checking the following files (mode=${mode}):"
echo "${EXISTING_FILES}" | awk '{ print "    " $0 }'

# ---------------------------------------------------------------------------
# Run pre-commit on the file list.
# ---------------------------------------------------------------------------
# `pre-commit run --files <list>` runs every applicable hook on the supplied
# files. Hooks with `pass_filenames: false` (mypy) still run scoped to
# their configured args (mypy → agentforge/) — which is what we want.
#
# We use `xargs -0` so files with spaces survive intact on Windows
# (the OneDrive path "C:\Users\Roy Harden\..." has a space).
files_arg=""
while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    files_arg+="${f}\0"
done <<< "${EXISTING_FILES}"

if [[ "${skip_mypy}" == "yes" ]]; then
    echo -ne "${files_arg}" | SKIP=mypy xargs -0 pre-commit run --files
else
    echo -ne "${files_arg}" | xargs -0 pre-commit run --files
fi
