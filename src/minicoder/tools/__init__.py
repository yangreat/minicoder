"""Tools for the coding agent."""

import asyncio
import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Result from a tool execution."""

    success: bool
    output: str
    error: str | None = None


class ReadFileTool:
    """Read file contents."""

    name = "read_file"
    description = "Read the contents of a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file relative to repo root"}
        },
        "required": ["path"],
    }

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    async def execute(self, path: str) -> ToolResult:
        """Execute the tool."""
        try:
            file_path = self.repo_path / path
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            content = file_path.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class WriteFileTool:
    """Write content to a file."""

    name = "write_file"
    description = "Write content to a file, creating it if it doesn't exist"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file relative to repo root"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    async def execute(self, path: str, content: str) -> ToolResult:
        """Execute the tool."""
        try:
            file_path = self.repo_path / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Successfully wrote to {path}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class ApplyPatchTool:
    """Apply a unified diff patch or search/replace edit."""

    name = "apply_patch"
    description = "Apply a patch using unified diff format or search/replace"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file relative to repo root"},
            "patch": {
                "type": "string",
                "description": "Unified diff patch or search/replace in format SEARCH:\n...\nREPLACE:\n...",
            },
        },
        "required": ["path", "patch"],
    }

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    async def execute(self, path: str, patch: str) -> ToolResult:
        """Execute the tool."""
        try:
            file_path = self.repo_path / path
            if not file_path.exists():
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            original = file_path.read_text(encoding="utf-8")

            if "SEARCH:" in patch and "REPLACE:" in patch:
                result = self._apply_search_replace(original, patch)
            else:
                result = self._apply_unified_diff(original, patch)

            if result.success:
                file_path.write_text(result.output, encoding="utf-8")

            return result
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _apply_search_replace(self, original: str, patch: str) -> ToolResult:
        """Apply search/replace patch."""
        parts = patch.split("REPLACE:", 1)
        if len(parts) != 2:
            return ToolResult(success=False, output="", error="Invalid search/replace format")

        search = parts[0].replace("SEARCH:", "").strip()
        replace = parts[1].strip()

        if search not in original:
            return ToolResult(success=False, output="", error="Search string not found")

        modified = original.replace(search, replace, 1)
        return ToolResult(success=True, output=modified)

    def _apply_unified_diff(self, original: str, patch: str) -> ToolResult:
        """Apply unified diff patch."""
        try:
            original.splitlines(keepends=True)
            patch_lines = patch.splitlines(keepends=True)

            result_lines = list(difflib.restore(patch_lines, 2))
            modified = "".join(result_lines)

            return ToolResult(success=True, output=modified)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to apply patch: {e}")


class RunShellTool:
    """Run a shell command."""

    name = "run_shell"
    description = "Execute a shell command in the repo directory"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default: 30)",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    def __init__(self, repo_path: Path, use_docker: bool = False, max_output_size: int = 10000):
        self.repo_path = repo_path
        self.use_docker = use_docker
        self.max_output_size = max_output_size

    async def execute(self, command: str, timeout: float = 30.0) -> ToolResult:
        """Execute the tool."""
        try:
            if self.use_docker:
                return await self._execute_docker(command, timeout)
            else:
                return await self._execute_local(command, timeout)
        except asyncio.TimeoutError:
            return ToolResult(success=False, output="", error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def _execute_local(self, command: str, timeout: float) -> ToolResult:
        """Execute command locally."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.repo_path,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        output = stdout.decode("utf-8", errors="replace")
        error = stderr.decode("utf-8", errors="replace")

        if len(output) > self.max_output_size:
            output = (
                output[: self.max_output_size]
                + f"\n... (truncated, {len(output) - self.max_output_size} bytes omitted)"
            )

        combined = output
        if error:
            combined += f"\nSTDERR:\n{error}"

        success = proc.returncode == 0
        return ToolResult(
            success=success,
            output=combined,
            error=None if success else f"Command exited with code {proc.returncode}",
        )

    async def _execute_docker(self, command: str, timeout: float) -> ToolResult:
        """Execute command in Docker container."""
        try:
            import docker

            client = docker.from_env()
            container = client.containers.run(
                "python:3.11-slim",
                command=["sh", "-c", command],
                volumes={str(self.repo_path.absolute()): {"bind": "/workspace", "mode": "rw"}},
                working_dir="/workspace",
                detach=True,
                remove=True,
            )

            start_time = asyncio.get_event_loop().time()
            while container.status != "exited":
                if asyncio.get_event_loop().time() - start_time > timeout:
                    container.kill()
                    return ToolResult(
                        success=False, output="", error=f"Command timed out after {timeout}s"
                    )
                await asyncio.sleep(0.1)
                container.reload()

            logs = container.logs().decode("utf-8", errors="replace")
            success = container.attrs["State"]["ExitCode"] == 0

            return ToolResult(
                success=success,
                output=logs,
                error=None if success else f"Command exited with code {container.attrs['State']['ExitCode']}",
            )
        except ImportError:
            return ToolResult(
                success=False,
                output="",
                error="Docker support not installed. Install with: pip install minicoder[docker]",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class SearchCodeTool:
    """Search code using ripgrep or fallback."""

    name = "search_code"
    description = "Search for a pattern in code files using regex"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "file_pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter files (e.g., '*.py')",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    async def execute(self, pattern: str, file_pattern: str | None = None) -> ToolResult:
        """Execute the tool."""
        try:
            if self._has_ripgrep():
                return await self._search_ripgrep(pattern, file_pattern)
            else:
                return await self._search_python(pattern, file_pattern)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        try:
            subprocess.run(["rg", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    async def _search_ripgrep(self, pattern: str, file_pattern: str | None) -> ToolResult:
        """Search using ripgrep."""
        cmd = ["rg", "--line-number", "--no-heading", "--color", "never", pattern]
        if file_pattern:
            cmd.extend(["-g", file_pattern])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.repo_path,
        )

        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            return ToolResult(success=True, output=output)
        elif proc.returncode == 1:
            return ToolResult(success=True, output="No matches found")
        else:
            return ToolResult(success=False, output="", error=stderr.decode("utf-8"))

    async def _search_python(self, pattern: str, file_pattern: str | None) -> ToolResult:
        """Fallback search using Python."""
        regex = re.compile(pattern)
        results = []

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for file in files:
                if file_pattern and not self._match_glob(file, file_pattern):
                    continue

                file_path = Path(root) / file
                try:
                    content = file_path.read_text(encoding="utf-8")
                    for line_num, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            rel_path = file_path.relative_to(self.repo_path)
                            results.append(f"{rel_path}:{line_num}:{line.strip()}")
                except (UnicodeDecodeError, PermissionError):
                    continue

        output = "\n".join(results) if results else "No matches found"
        return ToolResult(success=True, output=output)

    def _match_glob(self, filename: str, pattern: str) -> bool:
        """Simple glob matching."""
        import fnmatch

        return fnmatch.fnmatch(filename, pattern)


class ListFilesTool:
    """List files in the repository."""

    name = "list_files"
    description = "List files in a directory (non-recursive) or matching a pattern"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to repo root (default: '.')",
                "default": ".",
            },
            "pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter files",
            },
        },
    }

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    async def execute(self, path: str = ".", pattern: str | None = None) -> ToolResult:
        """Execute the tool."""
        try:
            dir_path = self.repo_path / path
            if not dir_path.exists():
                return ToolResult(success=False, output="", error=f"Directory not found: {path}")

            if not dir_path.is_dir():
                return ToolResult(success=False, output="", error=f"Not a directory: {path}")

            files = []
            for item in sorted(dir_path.iterdir()):
                if pattern:
                    import fnmatch

                    if not fnmatch.fnmatch(item.name, pattern):
                        continue

                rel_path = item.relative_to(self.repo_path)
                if item.is_dir():
                    files.append(f"{rel_path}/")
                else:
                    files.append(str(rel_path))

            output = "\n".join(files) if files else "No files found"
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


def get_all_tools(repo_path: Path, use_docker: bool = False) -> list[Any]:
    """Get all available tools."""
    return [
        ReadFileTool(repo_path),
        WriteFileTool(repo_path),
        ApplyPatchTool(repo_path),
        RunShellTool(repo_path, use_docker=use_docker),
        SearchCodeTool(repo_path),
        ListFilesTool(repo_path),
    ]
