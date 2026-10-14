"""Tests for test-file protection."""

from pathlib import Path

import pytest

from minicoder.tools import ApplyPatchTool, WriteFileTool
from minicoder.tools.guard import TestFileGuard


def test_detects_test_paths() -> None:
    guard = TestFileGuard("block")
    assert guard.is_test_path("test_calculator.py")
    assert guard.is_test_path("foo_test.py")
    assert guard.is_test_path("tests/test_x.py")
    assert guard.is_test_path("conftest.py")
    assert not guard.is_test_path("calculator.py")
    assert not guard.is_test_path("src/app.py")


@pytest.mark.asyncio
async def test_block_write_test_file(tmp_path: Path) -> None:
    guard = TestFileGuard("block")
    tool = WriteFileTool(tmp_path, test_guard=guard)
    result = await tool.execute("test_foo.py", "def test_x(): pass\n")
    assert not result.success
    assert "Refused" in (result.error or "")
    assert not (tmp_path / "test_foo.py").exists()


@pytest.mark.asyncio
async def test_block_allows_source(tmp_path: Path) -> None:
    guard = TestFileGuard("block")
    tool = WriteFileTool(tmp_path, test_guard=guard)
    result = await tool.execute("app.py", "x = 1\n")
    assert result.success
    assert (tmp_path / "app.py").read_text() == "x = 1\n"


@pytest.mark.asyncio
async def test_flag_allows_but_warns(tmp_path: Path) -> None:
    guard = TestFileGuard("flag")
    tool = WriteFileTool(tmp_path, test_guard=guard)
    result = await tool.execute("test_foo.py", "def test_x(): pass\n")
    assert result.success
    assert "WARNING" in result.output
    assert "test_foo.py" in guard.flagged
    assert (tmp_path / "test_foo.py").exists()


@pytest.mark.asyncio
async def test_block_apply_patch_to_tests(tmp_path: Path) -> None:
    (tmp_path / "test_app.py").write_text("assert False\n")
    guard = TestFileGuard("block")
    tool = ApplyPatchTool(tmp_path, test_guard=guard)
    result = await tool.execute(
        "test_app.py", "SEARCH:\nassert False\nREPLACE:\nassert True"
    )
    assert not result.success
    assert (tmp_path / "test_app.py").read_text() == "assert False\n"


def test_invalid_mode() -> None:
    with pytest.raises(ValueError):
        TestFileGuard("delete")
