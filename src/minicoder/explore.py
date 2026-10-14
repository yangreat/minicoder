"""Deterministic repo exploration used by the multi-agent planner."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _isolated_pytest_env() -> dict[str, str]:
    """Do not inherit the parent pytest's addopts/coverage plugins."""
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


SKIP_DIRS = {
    ".git",
    ".minicoder",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}

MAX_TREE_ENTRIES = 80
MAX_FILE_CHARS = 2500
MAX_TEST_OUTPUT = 8000


@dataclass
class ExplorationNotes:
    """Snapshot of the repo gathered before LLM planning."""

    file_tree: str = ""
    test_output: str = ""
    failing_tests: list[str] = field(default_factory=list)
    related_files: dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def filter_failures(self, wanted: list[str]) -> str:
        """Return pytest lines that mention any of ``wanted`` tests/files."""
        if not wanted:
            return self.test_output[:MAX_TEST_OUTPUT]
        needles = [w.strip() for w in wanted if w and w.strip()]
        if not needles:
            return self.test_output[:MAX_TEST_OUTPUT]
        kept: list[str] = []
        for line in self.test_output.splitlines():
            if any(n in line for n in needles):
                kept.append(line)
        if not kept:
            return self.test_output[:MAX_TEST_OUTPUT]
        return "\n".join(kept)[:MAX_TEST_OUTPUT]


class RepoExplorer:
    """Walk the tree, run tests, and collect related source files."""

    def explore(self, repo_path: Path) -> ExplorationNotes:
        root = Path(repo_path)
        tree = _file_tree(root)
        test_output, failing = _run_pytest(root)
        related = _related_files(root, failing, test_output)
        notes = ExplorationNotes(
            file_tree=tree,
            test_output=test_output,
            failing_tests=failing,
            related_files=related,
        )
        notes.summary = _format_summary(notes)
        return notes


def _file_tree(root: Path) -> str:
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if _should_skip(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        entries.append(rel + ("/" if path.is_dir() else ""))
        if len(entries) >= MAX_TREE_ENTRIES:
            entries.append("... (truncated)")
            break
    return "\n".join(entries) if entries else "(empty repo)"


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in SKIP_DIRS or part.startswith(".") for part in rel_parts)


def _run_pytest(root: Path) -> tuple[str, list[str]]:
    test_files = [
        p
        for p in root.rglob("*.py")
        if not _should_skip(p, root) and _looks_like_test(p.name)
    ]
    if not test_files:
        return "(no test files found; pytest skipped)", []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            env=_isolated_pytest_env(),
        )
    except subprocess.TimeoutExpired:
        return "pytest timed out", []
    except Exception as exc:
        return f"pytest failed to start: {exc}", []
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    text = text[:MAX_TEST_OUTPUT]
    failing = _parse_failing_tests(text)
    return text or f"pytest exit {result.returncode}", failing


def _looks_like_test(name: str) -> bool:
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


_FAILED_NODE = re.compile(
    r"^(FAILED|ERROR)\s+(\S+)",
    re.MULTILINE,
)
_FAILED_SUMMARY = re.compile(
    r"^(\S+::\S+)\s+FAILED",
    re.MULTILINE,
)


def _parse_failing_tests(output: str) -> list[str]:
    found: list[str] = []
    for match in _FAILED_NODE.finditer(output):
        found.append(match.group(2).strip())
    for match in _FAILED_SUMMARY.finditer(output):
        found.append(match.group(1).strip())
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _related_files(root: Path, failing: list[str], test_output: str) -> dict[str, str]:
    """Map likely source files and failing test files to truncated contents."""
    related: dict[str, str] = {}
    test_paths: list[Path] = []
    for node in failing:
        rel = node.split("::", 1)[0]
        candidate = root / rel
        if candidate.exists() and candidate.is_file():
            test_paths.append(candidate)
    if not test_paths:
        test_paths = [
            p
            for p in root.rglob("*.py")
            if not _should_skip(p, root) and _looks_like_test(p.name)
        ]

    for test_path in test_paths:
        rel = test_path.relative_to(root).as_posix()
        related[rel] = _read_truncated(test_path)
        for imported in _imports_from(test_path):
            src = _resolve_import(root, imported)
            if src is not None:
                related[src.relative_to(root).as_posix()] = _read_truncated(src)
        stem = test_path.stem
        if stem.startswith("test_"):
            module = stem[len("test_") :]
            for ext in (".py",):
                guess = root / f"{module}{ext}"
                if guess.exists():
                    related[guess.relative_to(root).as_posix()] = _read_truncated(guess)

    # Mention files named in pytest output that exist on disk.
    for match in re.finditer(r"([\w./-]+\.py)", test_output):
        candidate = root / match.group(1)
        if candidate.exists() and candidate.is_file() and not _should_skip(candidate, root):
            rel = candidate.relative_to(root).as_posix()
            related.setdefault(rel, _read_truncated(candidate))
    return related


def _imports_from(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name.split(".")[0])
    return names


def _resolve_import(root: Path, module: str) -> Path | None:
    py = root / f"{module}.py"
    if py.exists():
        return py
    pkg = root / module / "__init__.py"
    if pkg.exists():
        return pkg
    return None


def _read_truncated(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"(unreadable: {exc})"
    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + "\n... (truncated)"
    return text


def _format_summary(notes: ExplorationNotes) -> str:
    failing = ", ".join(notes.failing_tests) if notes.failing_tests else "(none parsed)"
    files = ", ".join(notes.related_files.keys()) or "(none)"
    return (
        f"## File tree\n{notes.file_tree}\n\n"
        f"## Failing tests\n{failing}\n\n"
        f"## Related files\n{files}\n\n"
        f"## Pytest output\n{notes.test_output[:MAX_TEST_OUTPUT]}"
    )
