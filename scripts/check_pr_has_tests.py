#!/usr/bin/env python3
"""check_pr_has_tests.py — CI gate enforcing the testing-discipline contract.

Adapted from EMR-SO/openemr/scripts/check_pr_has_tests.py. Rejects PRs that
touch platform code without adding at least one new test (`test_*.py`) or
eval case (`evals/cases/**/*.json` or `.yaml`).

The testing-discipline contract (see the `testing-discipline-team-brawlers-ai`
skill) says:

  - Code-touching PR -> add >=1 L1 unit test AND >=1 L4 case for any
    user-visible behavior change.
  - Bug-fix PR -> add at least one test/case that fails on the buggy
    revision and passes on the fix.
  - Refactor PR (no behavior change) -> may not require new tests if all
    five layers stay green; bypass with --allow-refactor and an explanation
    in the commit body.
  - Doc-only / config-only / workflow-only PR -> exempt.

Usage:
    python scripts/check_pr_has_tests.py --base origin/main --head HEAD
    python scripts/check_pr_has_tests.py            # defaults to origin/main..HEAD

Exit codes:
    0 = PR satisfies the rule (or is exempt).
    1 = PR touches code but adds zero tests / cases.
    2 = invocation error (bad args, git failure).
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from collections.abc import Iterable

# ---------------------------------------------------------------------------
# File-classification rules.
# ---------------------------------------------------------------------------
# Doc-only / config-only / workflow-only file globs. Touching any of these
# alone exempts a PR from the test-required rule. Order matters: more
# specific rules first.
EXEMPT_GLOBS: tuple[str, ...] = (
    "*.md",
    "*.txt",
    "*.rst",
    "LICENSE",
    "LICENSE.*",
    "CODEOWNERS",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "agentdocs/**",
    "humanrunbooks/**",
    "planning/**",
    "reports/**",
    "data/**",
    ".github/**",  # workflow / config changes route through actionlint
    ".pre-commit-config.yaml",
    ".codespellrc",
    "pyproject.toml",  # config-only — but watch for source dep churn
    "poetry.lock",
    "alembic.ini",
    "config/**",
)

# Globs that COUNT as "added a test" when the PR introduces them.
TEST_GLOBS: tuple[str, ...] = (
    "tests/**/test_*.py",
    "tests/**/*_test.py",
    "tests/**/conftest.py",  # new fixtures count as test additions
    "evals/cases/**/*.json",
    "evals/cases/**/*.yaml",
    "evals/cases/**/*.yml",
)

# Globs that constitute "platform code" — touching these requires tests.
CODE_GLOBS: tuple[str, ...] = (
    "agentforge/**/*.py",
    "scripts/**/*.py",
    "scripts/**/*.sh",
    "scripts/**/*.ps1",
)

# The cloned target under openemr/ is read-only; we don't gate on it.
READ_ONLY_GLOBS: tuple[str, ...] = ("openemr/**",)


def matches_any(path: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in globs)


def git_diff_file_list(base: str, head: str) -> list[str]:
    """Return files added/modified/renamed between base..head."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}..{head}"],
            text=True,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        print(f"git diff failed: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [line.strip() for line in out.splitlines() if line.strip()]


def git_diff_added_lines_count(base: str, head: str, path: str) -> int:
    """Return number of lines added in `path` between base..head.

    Used to distinguish "added a new test_* function" from "touched a test
    file but only deleted a function." For first-cut purposes, any added
    line in a test/case file counts as a new test.
    """
    try:
        out = subprocess.check_output(
            ["git", "diff", "--numstat", f"{base}..{head}", "--", path],
            text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            return int(parts[0])
    return 0


def classify(path: str) -> str:
    """Return one of: 'exempt', 'read_only', 'test', 'code', 'other'."""
    # Read-only subtree wins over everything else.
    if matches_any(path, READ_ONLY_GLOBS):
        return "read_only"
    if matches_any(path, TEST_GLOBS):
        return "test"
    if matches_any(path, EXEMPT_GLOBS):
        return "exempt"
    if matches_any(path, CODE_GLOBS):
        return "code"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="git ref for the merge-base (default: origin/main)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="git ref for the PR tip (default: HEAD)",
    )
    parser.add_argument(
        "--allow-refactor",
        action="store_true",
        help="Bypass the gate. Commit body MUST explain why. "
        "See testing-discipline skill: 'Refactor PR (no behavior change)'.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file classification on success.",
    )
    args = parser.parse_args()

    files = git_diff_file_list(args.base, args.head)
    if not files:
        print(f"No files changed between {args.base}..{args.head}. Nothing to gate.")
        return 0

    buckets: dict[str, list[str]] = {
        "exempt": [],
        "read_only": [],
        "test": [],
        "code": [],
        "other": [],
    }
    for f in files:
        buckets[classify(f)].append(f)

    code_touched = bool(buckets["code"]) or bool(buckets["other"])
    # Tests count only if the PR ADDED lines to them (deleting a test
    # doesn't satisfy "added a test"). For each `test` bucket file, sum
    # added lines and require >0 across the bucket.
    tests_added_lines = sum(
        git_diff_added_lines_count(args.base, args.head, f) for f in buckets["test"]
    )
    tests_added = tests_added_lines > 0

    if not args.quiet:
        print(f"Files changed between {args.base}..{args.head}:")
        for label in ("code", "test", "exempt", "read_only", "other"):
            for f in buckets[label]:
                marker = {
                    "code": "[CODE]",
                    "test": "[TEST]",
                    "exempt": "[EXEMPT]",
                    "read_only": "[RO]",
                    "other": "[OTHER]",
                }[label]
                print(f"  {marker:8} {f}")
        print()

    if not code_touched:
        print("OK: no code changes (exempt + read-only + tests only).")
        return 0

    if tests_added:
        print(f"OK: code change accompanied by {tests_added_lines} added test/case lines.")
        return 0

    if args.allow_refactor:
        print("OK: --allow-refactor passed. Commit body MUST justify; reviewer must enforce.")
        return 0

    print()
    print("FAIL: code change WITHOUT new tests or eval cases.")
    print()
    print("The testing-discipline-team-brawlers-ai skill requires one of:")
    print("  - >=1 added test:  tests/**/test_*.py  or  tests/**/*_test.py")
    print("  - >=1 added eval case:  evals/cases/**/*.json|yaml|yml")
    print()
    print("If this is a pure refactor with no behavior change, pass --allow-refactor")
    print("AND document the reasoning in the commit body. See the skill for the rule.")
    print()
    print("Bug-fix PRs MUST add at least one test/case that fails on the buggy")
    print("revision and passes on the fix (set 'what_bug_this_catches' on the case).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
