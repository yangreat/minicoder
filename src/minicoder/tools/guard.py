"""Guard that blocks or flags edits to test files during benchmarks."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_TEST_PATTERNS = [
    "test_*.py",
    "*_test.py",
    "*_tests.py",
    "conftest.py",
    "tests/**",
    "test/**",
    "**/test_*.py",
    "**/tests/**",
    "**/test/**",
    "**/conftest.py",
]


class TestFileGuard:
    """Configurable protection for test files.

    Modes:
      * ``off``: allow all edits (default for interactive use)
      * ``block``: refuse writes/patches to test files
      * ``flag``: allow the edit but record a warning (and tag the result)
    """

    __test__ = False

    def __init__(self, mode: str = "off", patterns: list[str] | None = None):
        if mode not in ("off", "block", "flag"):
            raise ValueError(f"Invalid protect_tests mode: {mode!r}")
        self.mode = mode
        self.patterns = list(patterns or DEFAULT_TEST_PATTERNS)
        self.flagged: list[str] = []

    def is_test_path(self, path: str) -> bool:
        """Return True if ``path`` (relative to the repo) looks like a test file."""
        posix = path.replace("\\", "/").lstrip("./")
        name = Path(posix).name
        parts = posix.split("/")

        if name == "conftest.py":
            return True
        if name.startswith("test_") and name.endswith(".py"):
            return True
        if name.endswith("_test.py") or name.endswith("_tests.py"):
            return True
        if "tests" in parts or "test" in parts:
            return True

        for pat in self.patterns:
            if _match_pattern(posix, name, pat):
                return True
        return False

    def check(self, path: str) -> str | None:
        """Return an error message if the edit must be blocked, else None."""
        if self.mode == "off" or not self.is_test_path(path):
            return None
        if self.mode == "block":
            return (
                f"Refused to modify test file '{path}'. "
                "Benchmark tests are protected; edit production code instead."
            )
        if path not in self.flagged:
            self.flagged.append(path)
        return None

    def warning_for(self, path: str) -> str | None:
        """Return a warning string when mode is ``flag`` and ``path`` is a test."""
        if self.mode == "flag" and self.is_test_path(path):
            if path not in self.flagged:
                self.flagged.append(path)
            return f"WARNING: modified test file '{path}'"
        return None


def _match_pattern(posix: str, name: str, pattern: str) -> bool:
    if fnmatch(name, pattern) or fnmatch(posix, pattern):
        return True
    if "**" in pattern:
        regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        if re.fullmatch(regex, posix):
            return True
    return False
