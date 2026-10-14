"""Tests for unified-diff and SEARCH/REPLACE application."""

from pathlib import Path

import pytest

from minicoder.tools import ApplyPatchTool
from minicoder.tools.patch import PatchError, apply_patch_text, apply_unified_diff

CALCULATOR = '''"""Bug: division by zero raises ZeroDivisionError instead of ValueError."""


def calculator(a: float, b: float, operation: str) -> float:
    """Perform calculation."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        return a / b
    else:
        raise ValueError(f"Unknown operation: {operation}")
'''


def test_search_replace_basic() -> None:
    original = "def hello():\n    print('Hello')\n"
    patch = "SEARCH:\nprint('Hello')\nREPLACE:\nprint('Hello, World!')"
    out = apply_patch_text(original, patch)
    assert "Hello, World!" in out
    assert "def hello():" in out


def test_search_replace_multiple_blocks() -> None:
    original = "a = 1\nb = 2\n"
    patch = "SEARCH:\na = 1\nREPLACE:\na = 10\nSEARCH:\nb = 2\nREPLACE:\nb = 20"
    out = apply_patch_text(original, patch)
    assert out == "a = 10\nb = 20\n" or "a = 10" in out and "b = 20" in out


def test_search_replace_not_found() -> None:
    with pytest.raises(PatchError, match="not found"):
        apply_patch_text("abc", "SEARCH:\nzzz\nREPLACE:\nyyy")


def test_search_replace_ambiguous() -> None:
    with pytest.raises(PatchError, match="times"):
        apply_patch_text("foo\nfoo\n", "SEARCH:\nfoo\nREPLACE:\nbar")


def test_search_replace_empty_search() -> None:
    with pytest.raises(PatchError, match="Empty SEARCH"):
        apply_patch_text("abc", "SEARCH:\n\nREPLACE:\nxyz")


def test_search_without_replace() -> None:
    with pytest.raises(PatchError, match="neither a unified diff|without matching REPLACE"):
        apply_patch_text("abc", "SEARCH:\nfoo")


def test_search_replace_whitespace_flexible() -> None:
    original = "def f():\n    return 1\n"
    patch = "SEARCH:\n    return 1  \nREPLACE:\n    return 2"
    out = apply_patch_text(original, patch)
    assert "return 2" in out


def test_empty_patch() -> None:
    with pytest.raises(PatchError, match="Empty"):
        apply_patch_text("abc", "   \n")


def test_garbage_patch() -> None:
    with pytest.raises(PatchError, match="neither"):
        apply_patch_text("abc\n", "this is not a patch at all")


def test_malformed_hunk_header() -> None:
    with pytest.raises(PatchError, match="Malformed hunk header"):
        apply_unified_diff("abc\n", "@@ not a header @@\n-abc\n+def\n")


def test_malformed_hunk_line() -> None:
    with pytest.raises(PatchError, match="Malformed hunk line"):
        apply_unified_diff("abc\n", "@@ -1,1 +1,1 @@\nthis has no prefix\n")


def test_no_hunks() -> None:
    with pytest.raises(PatchError, match="No hunks"):
        apply_unified_diff("abc\n", "--- a/x\n+++ b/x\n")


def test_hunk_mismatch() -> None:
    original = "alpha\nbeta\ngamma\n"
    patch = "@@ -1,2 +1,2 @@\n-nope\n-nope\n+yes\n+yes\n"
    with pytest.raises(PatchError, match="does not match"):
        apply_unified_diff(original, patch)


def test_unified_diff_applies_and_keeps_rest_of_file() -> None:
    """Regression: difflib.restore used to replace the file with a hunk fragment."""
    patch = """--- a/calculator.py
+++ b/calculator.py
@@ -12,2 +12,4 @@
     elif operation == "divide":
+        if b == 0:
+            raise ValueError("Cannot divide by zero")
         return a / b
"""
    out = apply_patch_text(CALCULATOR, patch)
    assert out.startswith('"""Bug:')
    assert "def calculator" in out
    assert "if b == 0:" in out
    assert 'raise ValueError("Cannot divide by zero")' in out
    assert "elif operation == \"multiply\":" in out
    assert not out.lstrip().startswith("elif operation ==")


def test_unified_diff_wrong_line_numbers_still_match_context() -> None:
    patch = """@@ -99,3 +99,4 @@
     elif operation == "divide":
+        if b == 0:
+            raise ValueError("Cannot divide by zero")
         return a / b
     else:
"""
    out = apply_unified_diff(CALCULATOR, patch)
    assert "Cannot divide by zero" in out
    assert "def calculator" in out


def test_unified_diff_multiple_hunks() -> None:
    original = "one\ntwo\nthree\nfour\n"
    patch = """@@ -1,1 +1,1 @@
-one
+ONE
@@ -3,1 +3,1 @@
-three
+THREE
"""
    out = apply_unified_diff(original, patch)
    assert out.splitlines() == ["ONE", "two", "THREE", "four"]


def test_unified_diff_insertion_at_start() -> None:
    original = "body\n"
    patch = "@@ -0,0 +1,1 @@\n+header\n"
    out = apply_unified_diff(original, patch)
    assert out.startswith("header")
    assert "body" in out


@pytest.mark.asyncio
async def test_apply_patch_tool_unified_diff(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text(CALCULATOR)
    tool = ApplyPatchTool(tmp_path)
    patch = """@@ -12,2 +12,4 @@
     elif operation == "divide":
+        if b == 0:
+            raise ValueError("Cannot divide by zero")
         return a / b
"""
    result = await tool.execute("calculator.py", patch)
    assert result.success, result.error
    text = (tmp_path / "calculator.py").read_text()
    assert "Cannot divide by zero" in text
    assert "def calculator" in text


@pytest.mark.asyncio
async def test_apply_patch_tool_malformed(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    tool = ApplyPatchTool(tmp_path)
    result = await tool.execute("a.py", "not a patch")
    assert not result.success
    assert result.error
    assert (tmp_path / "a.py").read_text() == "x = 1\n"


@pytest.mark.asyncio
async def test_apply_patch_missing_file(tmp_path: Path) -> None:
    tool = ApplyPatchTool(tmp_path)
    result = await tool.execute("nope.py", "SEARCH:\na\nREPLACE:\nb")
    assert not result.success
    assert "not found" in (result.error or "").lower()
