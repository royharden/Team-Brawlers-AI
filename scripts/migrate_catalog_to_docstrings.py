#!/usr/bin/env python3
"""migrate_catalog_to_docstrings.py — one-shot: move CATALOG.md prose into docstrings.

The existing tests/CATALOG.md was hand-curated with prose richer than the
test docstrings carry. The testing-discipline contract says the catalog
must be auto-generated from docstrings. This script bridges the gap once:

    1. Parse tests/CATALOG.md, build a map of (file, testname) -> description.
    2. For each test function in tests/, if it has NO docstring, inject
       a single-line docstring containing the CATALOG description.
    3. If it already has a docstring whose first line matches CATALOG,
       no-op (idempotent).
    4. If it already has a docstring that DOES NOT match CATALOG, report
       the conflict and skip. Use --force-overwrite to replace.

After running --apply, run `scripts/regenerate_test_catalog.py` to produce
the auto-generated catalog. The pre-push freshness gate should then pass.

Usage:
    python scripts/migrate_catalog_to_docstrings.py             # dry-run (default)
    python scripts/migrate_catalog_to_docstrings.py --apply     # write changes
    python scripts/migrate_catalog_to_docstrings.py --apply --force-overwrite

Exit codes:
    0 = ran cleanly (dry-run or apply).
    1 = parse / file-not-found problems.
    2 = invocation error.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys

# Windows console defaults to cp1252; CATALOG.md contains math symbols (>=, etc).
# Re-attach stdout/stderr in UTF-8 so we don't crash on print().
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
CATALOG_PATH = TESTS_DIR / "CATALOG.md"

# Match catalog rows like:
#   | `tests/unit/test_pricing.py::test_resolve_models_anthropic_all_found` | `unit` | description... |
# Class-based form (less common but valid):
#   | `tests/unit/foo.py::TestClass::test_method` | `unit` | description... |
ROW_RE = re.compile(
    r"^\|\s*`(?P<path>tests/[^`]+\.py)::(?P<testid>[A-Za-z0-9_:]+)`\s*\|"
    r"\s*`?(?P<marker>[a-z?]+)`?\s*\|\s*(?P<desc>.+?)\s*\|\s*$"
)


def parse_catalog(path: Path) -> dict[tuple[str, str], str]:
    """Return {(rel_path, testid): description}. testid may be 'test_x' or 'TestC::test_y'."""
    out: dict[tuple[str, str], str] = {}
    if not path.exists():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        rel = m.group("path")
        testid = m.group("testid")
        desc = m.group("desc").strip()
        # Unescape the markdown-pipe-escape that regenerate_test_catalog applies.
        desc = desc.replace("\\|", "|")
        out[(rel, testid)] = desc
    return out


def find_function_in_tree(
    tree: ast.Module, testid: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Resolve a testid like 'test_foo' or 'TestClass::test_method' to its AST node."""
    if "::" in testid:
        class_name, method_name = testid.split("::", 1)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if (
                        isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                        and child.name == method_name
                    ):
                        return child
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == testid:
            return node
    return None


def existing_docstring_first_line(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    doc = ast.get_docstring(node, clean=True)
    if not doc:
        return None
    return doc.strip().splitlines()[0].strip().replace("|", "\\|")


def body_start_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return the source line number of the first statement in the function body."""
    return node.body[0].lineno


def body_indent(source_lines: list[str], body_lineno: int) -> str:
    """Return the leading whitespace of the function-body's first line."""
    line = source_lines[body_lineno - 1]
    return line[: len(line) - len(line.lstrip())]


def render_docstring(indent: str, desc: str) -> str:
    """Render a single-line triple-quoted docstring with correct indentation.

    Triple double-quotes are safe even when the description contains single
    or double quotes. We DO escape any literal triple-double-quote sequence
    by switching to triple single-quote in that case (rare).
    """
    if '"""' in desc:
        return f"{indent}'''{desc}'''\n"
    return f'{indent}"""{desc}"""\n'


def inject_docstring(
    source_lines: list[str],
    insert_at_line: int,
    indent: str,
    desc: str,
) -> list[str]:
    """Return new source-lines list with the docstring inserted at insert_at_line (1-indexed)."""
    new_line = render_docstring(indent, desc)
    new_lines = list(source_lines)
    new_lines.insert(insert_at_line - 1, new_line)
    return new_lines


def replace_existing_docstring(
    source_lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    desc: str,
) -> list[str]:
    """Replace the existing docstring node's lines with a fresh single-line docstring."""
    first = node.body[0]
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        raise RuntimeError(
            f"replace_existing_docstring called on non-docstring body at line {first.lineno}"
        )
    start = first.lineno - 1  # 0-indexed inclusive
    end = first.end_lineno  # 0-indexed exclusive (ast end_lineno is 1-indexed line of last)
    indent = body_indent(source_lines, first.lineno)
    new_line = render_docstring(indent, desc)
    new_lines = source_lines[:start] + [new_line] + source_lines[end:]
    return new_lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to disk (default: dry-run report only).",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Overwrite existing docstrings that conflict with CATALOG.md. "
        "Default: skip and report conflicts.",
    )
    args = parser.parse_args()

    catalog = parse_catalog(CATALOG_PATH)
    if not catalog:
        print(
            f"ERROR: no entries parsed from {CATALOG_PATH.relative_to(REPO_ROOT)}", file=sys.stderr
        )
        return 1
    print(f"Parsed {len(catalog)} CATALOG.md entries.")

    # Group catalog entries by file so we re-write each file once.
    by_file: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (rel_path, testid), desc in catalog.items():
        by_file[rel_path].append((testid, desc))

    stats = {
        "injected": 0,  # had no docstring -> we added one
        "already_matches": 0,  # docstring already matches CATALOG description
        "conflict_skipped": 0,  # docstring exists but differs; skipped (no --force)
        "conflict_overwrote": 0,  # --force replaced
        "function_missing": 0,  # CATALOG row's function not found in source
        "file_missing": 0,
    }
    file_changes: dict[Path, list[str]] = {}

    for rel_path, entries in sorted(by_file.items()):
        abs_path = REPO_ROOT / rel_path
        if not abs_path.exists():
            print(f"  [FILE MISSING] {rel_path} ({len(entries)} catalog entries)")
            stats["file_missing"] += len(entries)
            continue

        source = abs_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(abs_path))
        except SyntaxError as e:
            print(f"  [PARSE FAIL] {rel_path}: {e}", file=sys.stderr)
            stats["file_missing"] += len(entries)
            continue

        source_lines = source.splitlines(keepends=True)
        if source_lines and not source_lines[-1].endswith("\n"):
            source_lines[-1] += "\n"

        # Process entries TOP-DOWN by descending body_start_line so inserts
        # don't shift later line numbers. Build a list keyed by line number.
        nodes_with_desc: list[
            tuple[int, ast.FunctionDef | ast.AsyncFunctionDef, str, str, str]
        ] = []
        for testid, desc in entries:
            node = find_function_in_tree(tree, testid)
            if node is None:
                print(f"  [FUNC MISSING] {rel_path}::{testid}")
                stats["function_missing"] += 1
                continue
            existing = existing_docstring_first_line(node)
            esc_desc = desc.replace("|", "\\|")  # match how regenerator renders pipes
            if existing is None:
                action = "inject"
            elif existing == esc_desc:
                action = "match"
            else:
                action = "conflict"
            nodes_with_desc.append((node.body[0].lineno, node, desc, existing or "", action))

        # Descending sort by lineno so later inserts come first.
        nodes_with_desc.sort(key=lambda t: t[0], reverse=True)

        modified = False
        for _lineno, node, desc, existing, action in nodes_with_desc:
            if action == "match":
                stats["already_matches"] += 1
                continue
            if action == "inject":
                stats["injected"] += 1
                indent = body_indent(source_lines, node.body[0].lineno)
                source_lines = inject_docstring(
                    source_lines,
                    node.body[0].lineno,
                    indent,
                    desc,
                )
                modified = True
                continue
            if action == "conflict":
                if args.force_overwrite:
                    stats["conflict_overwrote"] += 1
                    source_lines = replace_existing_docstring(source_lines, node, desc)
                    modified = True
                else:
                    stats["conflict_skipped"] += 1
                    print(
                        f"  [CONFLICT] {rel_path}::{node.name}\n"
                        f"      existing: {existing[:80]}\n"
                        f"      CATALOG : {desc[:80]}"
                    )

        if modified:
            file_changes[abs_path] = source_lines

    print()
    print("Summary:")
    for k, v in stats.items():
        print(f"  {k:24} {v}")
    print(f"  files_to_modify        {len(file_changes)}")

    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to write changes.")
        return 0

    if not file_changes:
        print("\nNothing to write.")
        return 0

    for abs_path, new_lines in file_changes.items():
        abs_path.write_text("".join(new_lines), encoding="utf-8")
        print(f"  WROTE {abs_path.relative_to(REPO_ROOT)}")
    print()
    print(
        f"Wrote {len(file_changes)} files. Next steps:\n"
        f"  1. python scripts/regenerate_test_catalog.py\n"
        f"  2. python scripts/regenerate_test_catalog.py --check  # expect: OK\n"
        f"  3. ./scripts/precommit_changed_files.sh --all-files OR run gauntlet manually"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
