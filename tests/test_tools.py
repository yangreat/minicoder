"""Test tools."""

import pytest
from pathlib import Path

from minicoder.tools import (
    ApplyPatchTool,
    ListFilesTool,
    ReadFileTool,
    RunShellTool,
    SearchCodeTool,
    WriteFileTool,
)


@pytest.mark.asyncio
async def test_read_file(tmp_path: Path) -> None:
    """Test reading a file."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, world!")

    tool = ReadFileTool(tmp_path)
    result = await tool.execute("test.txt")

    assert result.success
    assert result.output == "Hello, world!"


@pytest.mark.asyncio
async def test_write_file(tmp_path: Path) -> None:
    """Test writing a file."""
    tool = WriteFileTool(tmp_path)
    result = await tool.execute("new_file.txt", "Test content")

    assert result.success

    created_file = tmp_path / "new_file.txt"
    assert created_file.exists()
    assert created_file.read_text() == "Test content"


@pytest.mark.asyncio
async def test_apply_search_replace(tmp_path: Path) -> None:
    """Test search/replace patch."""
    test_file = tmp_path / "code.py"
    test_file.write_text("def hello():\n    print('Hello')")

    tool = ApplyPatchTool(tmp_path)
    patch = "SEARCH:\nprint('Hello')\nREPLACE:\nprint('Hello, World!')"

    result = await tool.execute("code.py", patch)

    assert result.success
    content = test_file.read_text()
    assert "Hello, World!" in content


@pytest.mark.asyncio
async def test_run_shell(tmp_path: Path) -> None:
    """Test running a shell command."""
    tool = RunShellTool(tmp_path)
    result = await tool.execute("echo 'test'", timeout=5)

    assert result.success
    assert "test" in result.output


@pytest.mark.asyncio
async def test_search_code(tmp_path: Path) -> None:
    """Test code search."""
    test_file = tmp_path / "code.py"
    test_file.write_text("def hello():\n    return 'world'")

    tool = SearchCodeTool(tmp_path)
    result = await tool.execute("hello")

    assert result.success
    assert "code.py" in result.output or "No matches found" in result.output


@pytest.mark.asyncio
async def test_list_files(tmp_path: Path) -> None:
    """Test listing files."""
    (tmp_path / "file1.txt").write_text("content")
    (tmp_path / "file2.py").write_text("code")

    tool = ListFilesTool(tmp_path)
    result = await tool.execute(".")

    assert result.success
    assert "file1.txt" in result.output
    assert "file2.py" in result.output
