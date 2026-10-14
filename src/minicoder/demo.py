"""Scripted demo-mode scenario: fix the toy calculator divide-by-zero bug."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from minicoder.mock_llm import MockOpenAI, MockResponse, MockToolCall

CALCULATOR_RELATIVE = Path("benchmarks/toy_repos/calculator")

ORIGINAL_CALCULATOR = '''"""Bug: division by zero raises ZeroDivisionError instead of ValueError."""


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

BUGGY_DIVIDE = "    elif operation == \"divide\":\n        return a / b"

FIXED_DIVIDE = (
    "    elif operation == \"divide\":\n"
    "        if b == 0:\n"
    "            raise ValueError(\"Cannot divide by zero\")\n"
    "        return a / b"
)

CALCULATOR_PATCH = f"SEARCH:\n{BUGGY_DIVIDE}\nREPLACE:\n{FIXED_DIVIDE}"


def package_root() -> Path:
    """Return the MiniCoder project root (parent of src/)."""
    return Path(__file__).resolve().parents[2]


def toy_calculator_dir() -> Path:
    """Path to the bundled buggy calculator repo."""
    return package_root() / CALCULATOR_RELATIVE


def resolve_mock_repo(requested: Path) -> Path:
    """Use the toy calculator when the caller pointed at the project root."""
    requested = requested.resolve()
    if (requested / "calculator.py").exists():
        return requested

    nested = requested / CALCULATOR_RELATIVE
    if (nested / "calculator.py").exists():
        return nested.resolve()

    toy = toy_calculator_dir()
    if (toy / "calculator.py").exists():
        cwd = Path.cwd().resolve()
        if requested == cwd or requested == package_root():
            return toy.resolve()
    return requested


def demo_calculator_path(repo_path: Path) -> str:
    """Relative path the tools should edit."""
    if (repo_path / "calculator.py").exists():
        return "calculator.py"
    return str(CALCULATOR_RELATIVE / "calculator.py")


def build_demo_responses(repo_path: Path) -> list[MockResponse]:
    """Four-step script: inspect, patch, verify, finish."""
    calc = demo_calculator_path(repo_path)
    return [
        MockResponse(
            content=(
                "I'll inspect `calculator.py` to locate the divide-by-zero bug "
                "before changing anything."
            ),
            tool_calls=[
                MockToolCall(
                    id="call_read_1",
                    function_name="read_file",
                    arguments=json.dumps({"path": calc}),
                )
            ],
        ),
        MockResponse(
            content=(
                "Division does `return a / b` with no zero check. "
                "I'll apply a guard that raises ValueError when b == 0."
            ),
            tool_calls=[
                MockToolCall(
                    id="call_patch_1",
                    function_name="apply_patch",
                    arguments=json.dumps({"path": calc, "patch": CALCULATOR_PATCH}),
                )
            ],
        ),
        MockResponse(
            content="Patch applied. Re-reading the file to confirm the guard is in place.",
            tool_calls=[
                MockToolCall(
                    id="call_read_2",
                    function_name="read_file",
                    arguments=json.dumps({"path": calc}),
                )
            ],
        ),
        MockResponse(
            content="The divide-by-zero bug is fixed.",
            tool_calls=[
                MockToolCall(
                    id="call_finish",
                    function_name="finish",
                    arguments=json.dumps(
                        {
                            "message": (
                                "Added a zero-divisor check in calculator.py so "
                                "divide raises ValueError instead of crashing."
                            )
                        }
                    ),
                )
            ],
        ),
    ]


def build_demo_client(repo_path: Path) -> MockOpenAI:
    """Mock OpenAI client that plays the calculator-fix script."""
    return MockOpenAI(build_demo_responses(repo_path))


def restore_toy_calculator() -> None:
    """Write the original buggy calculator source back to the toy repo."""
    root = toy_calculator_dir()
    (root / "calculator.py").write_text(ORIGINAL_CALCULATOR)
    git_dir = root / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    minicoder_dir = root / ".minicoder"
    if minicoder_dir.exists():
        shutil.rmtree(minicoder_dir)
