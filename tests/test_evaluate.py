"""Tests for the evaluation harness and toy-repo invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.evaluate import (
    COMPRESSION_PRESETS,
    RunRecord,
    aggregate,
    build_parser,
    list_toy_tasks,
    pytest_ok,
    render_markdown,
    restore_test_files,
    run_one,
    snapshot_test_files,
)

TOY = Path(__file__).resolve().parent.parent / "benchmarks" / "toy_repos"


def test_ten_toy_repos_exist() -> None:
    tasks = list_toy_tasks(TOY)
    names = {t["name"] for t in tasks}
    assert len(names) >= 10
    for required in (
        "calculator",
        "text_stats",
        "inventory",
        "fizzbuzz",
        "palindrome",
        "roman",
        "url_join",
        "csv_stats",
        "lru_cache",
        "todo_store",
    ):
        assert required in names


@pytest.mark.parametrize("name", [
    "calculator",
    "text_stats",
    "inventory",
    "fizzbuzz",
    "palindrome",
    "roman",
    "url_join",
    "csv_stats",
    "lru_cache",
    "todo_store",
])
def test_toy_repo_fails_before_fix(name: str) -> None:
    ok, summary = pytest_ok(TOY / name)
    assert not ok, f"{name} tests already pass before a fix: {summary}"


@pytest.mark.asyncio
async def test_run_one_mock_does_not_pass_tests() -> None:
    rec = await run_one(
        task_name="calculator",
        src=TOY / "calculator",
        model="mock",
        base_url=None,
        api_key=None,
        compression="default",
        agent_mode="single",
        max_steps=5,
        protect_tests="block",
        request_timeout=5,
        max_retries=0,
        max_parallel=2,
        use_mock=True,
        repeat=1,
    )
    assert rec.baseline_tests_pass is False
    assert rec.tests_pass is False
    assert rec.tests_restored is True
    assert rec.agent_status == "success"


def test_calculator_passes_after_valueerror_guard(tmp_path: Path) -> None:
    src = (TOY / "calculator" / "calculator.py").read_text()
    dest = tmp_path / "calc"
    dest.mkdir()
    (dest / "calculator.py").write_text(
        src.replace(
            "    elif operation == \"divide\":\n        return a / b",
            "    elif operation == \"divide\":\n"
            "        if b == 0:\n"
            "            raise ValueError(\"Cannot divide by zero\")\n"
            "        return a / b",
        )
    )
    (dest / "test_calculator.py").write_text(
        (TOY / "calculator" / "test_calculator.py").read_text()
    )
    ok, summary = pytest_ok(dest)
    assert ok, summary


def test_snapshot_and_restore_tests(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "test_app.py").write_text("assert True\n")
    snaps = snapshot_test_files(tmp_path)
    assert "test_app.py" in snaps
    (tmp_path / "test_app.py").write_text("assert False  # rewritten by agent\n")
    (tmp_path / "test_extra.py").write_text("assert True\n")
    restore_test_files(tmp_path, snaps)
    assert (tmp_path / "test_app.py").read_text() == "assert True\n"
    assert not (tmp_path / "test_extra.py").exists()
    assert (tmp_path / "app.py").read_text() == "x = 1\n"


def test_parser_requires_model_without_mock() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    # default model comes from env; we only assert the flag exists and
    # compression/agent-mode defaults.
    assert args.compression == "default"
    assert args.agent_mode == "single"
    assert args.repeats == 1
    assert args.protect_tests == "block"
    assert set(COMPRESSION_PRESETS) == {"default", "off", "aggressive"}


def test_aggregate_mean_and_spread() -> None:
    rows = [
        RunRecord(
            config="default",
            task="calculator",
            model="m",
            repeat=1,
            agent_mode="single",
            baseline_tests_pass=False,
            tests_pass=True,
            tests_restored=True,
            agent_status="success",
            agent_message="",
            steps=4,
            llm_calls=4,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            compressions_triggered=0,
            wall_s=1.0,
            pytest_summary="ok",
        ),
        RunRecord(
            config="default",
            task="calculator",
            model="m",
            repeat=2,
            agent_mode="single",
            baseline_tests_pass=False,
            tests_pass=False,
            tests_restored=True,
            agent_status="failed",
            agent_message="",
            steps=8,
            llm_calls=8,
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            compressions_triggered=2,
            wall_s=3.0,
            pytest_summary="fail",
        ),
    ]
    summary = aggregate(rows)
    key = "m / default / single"
    assert key in summary
    assert summary[key]["tests_pass"] == "1/2"
    assert summary[key]["steps"]["mean"] == 6.0
    assert summary[key]["steps"]["min"] == 4.0
    assert summary[key]["steps"]["max"] == 8.0
    md = render_markdown(rows, summary)
    assert "calculator" in md
    assert "mean" in md.lower() or "±" in md
    json.dumps(summary)
