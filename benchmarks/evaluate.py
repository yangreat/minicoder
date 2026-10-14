"""Evaluation CLI for MiniCoder toy-repo benchmarks.

Copies each task into a fresh temp directory, runs the agent, restores the
original tests, then grades with pytest. Model / base URL come from flags or
environment variables — nothing is hardcoded to gpt-4.

Example (OpenAI-compatible endpoint)::

    export OPENAI_API_KEY="sk-..."
    export OPENAI_BASE_URL="https://api.example.com/v1"

    python benchmarks/evaluate.py \\
      --model "$OPENAI_MODEL" \\
      --base-url "$OPENAI_BASE_URL" \\
      --compression default \\
      --agent-mode single \\
      --repeats 1 \\
      --max-steps 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from minicoder.agent import CodingAgent
from minicoder.state import StateManager
from minicoder.tools.guard import TestFileGuard

DEFAULT_TASK = (
    "Fix the bug in this repository. Read README.md for context and make all tests pass."
)

COMPRESSION_PRESETS: dict[str, dict[str, int]] = {
    "default": {"max_tokens": 8000, "keep_recent": 5},
    "off": {"max_tokens": 10**9, "keep_recent": 5},
    "aggressive": {"max_tokens": 1500, "keep_recent": 5},
}

TOY_REPOS_DIR = Path(__file__).resolve().parent / "toy_repos"


@dataclass
class RunRecord:
    """One agent run on one task."""

    config: str
    task: str
    model: str
    repeat: int
    agent_mode: str
    baseline_tests_pass: bool
    tests_pass: bool
    tests_restored: bool
    agent_status: str
    agent_message: str
    steps: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    compressions_triggered: int
    wall_s: float
    pytest_summary: str
    test_files_flagged: list[str] = field(default_factory=list)
    error: str | None = None
    fell_back_to_single: bool = False
    true_multi: bool = False
    plan_source: str = ""
    worker_stats: list[dict[str, Any]] = field(default_factory=list)
    file_conflicts: list[dict[str, Any]] = field(default_factory=list)


def list_toy_tasks(toy_dir: Path | None = None) -> list[dict[str, str]]:
    """Discover toy repos that have a README.md."""
    root = toy_dir or TOY_REPOS_DIR
    tasks: list[dict[str, str]] = []
    if not root.exists():
        return tasks
    for repo_dir in sorted(root.iterdir()):
        if repo_dir.is_dir() and (repo_dir / "README.md").exists():
            tasks.append(
                {
                    "name": repo_dir.name,
                    "path": str(repo_dir),
                    "task": DEFAULT_TASK,
                }
            )
    return tasks


def pytest_ok(cwd: Path, timeout: int = 60) -> tuple[bool, str]:
    """Run pytest in ``cwd``. Returns (passed, last-line summary)."""
    try:
        env = os.environ.copy()
        env.pop("PYTEST_ADDOPTS", None)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "pytest timed out"
    except Exception as exc:
        return False, f"pytest failed to start: {exc}"
    text = (result.stdout or "") + (result.stderr or "")
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else f"exit {result.returncode}"
    return result.returncode == 0, summary


def snapshot_test_files(work: Path) -> dict[str, str]:
    """Capture original test-file contents relative to ``work``."""
    guard = TestFileGuard("block")
    snaps: dict[str, str] = {}
    for path in work.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(work).as_posix()
        if rel.startswith(".git/") or rel.startswith(".minicoder/"):
            continue
        if guard.is_test_path(rel):
            snaps[rel] = path.read_text(encoding="utf-8")
    return snaps


def restore_test_files(work: Path, snaps: dict[str, str]) -> None:
    """Write original tests back and drop extra test files the agent added."""
    guard = TestFileGuard("block")
    for rel, content in snaps.items():
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    for path in list(work.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(work).as_posix()
        if rel.startswith(".git/") or rel.startswith(".minicoder/"):
            continue
        if guard.is_test_path(rel) and rel not in snaps:
            path.unlink()


def _init_git(work: Path) -> None:
    for args in (
        ["init", "-q"],
        ["-c", "user.email=eval@minicoder", "-c", "user.name=eval", "add", "-A"],
        [
            "-c",
            "user.email=eval@minicoder",
            "-c",
            "user.name=eval",
            "commit",
            "-qm",
            "init",
        ],
    ):
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)


def _wrap_client_usage(agent: CodingAgent) -> dict[str, Any]:
    """Instrument the LLM client to count tokens and compression events."""
    usage: dict[str, Any] = {
        "prompt": 0,
        "completion": 0,
        "calls": 0,
        "compressions": 0,
        "served_model": None,
    }
    orig_create = agent.client.chat.completions.create

    async def create(**kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        if len(messages) < len(agent.context.messages):
            usage["compressions"] += 1
        result = await orig_create(**kwargs)
        usage["calls"] += 1
        usage["served_model"] = getattr(result, "model", None)
        usage_obj = getattr(result, "usage", None)
        if usage_obj is not None:
            usage["prompt"] += int(getattr(usage_obj, "prompt_tokens", 0) or 0)
            usage["completion"] += int(getattr(usage_obj, "completion_tokens", 0) or 0)
        return result

    agent.client.chat.completions.create = create  # type: ignore[method-assign]
    return usage


async def run_one(
    *,
    task_name: str,
    src: Path,
    model: str,
    base_url: str | None,
    api_key: str | None,
    compression: str,
    agent_mode: str,
    max_steps: int,
    protect_tests: str,
    request_timeout: float,
    max_retries: int,
    max_parallel: int,
    use_mock: bool,
    repeat: int,
) -> RunRecord:
    work_root = Path(tempfile.mkdtemp(prefix=f"mc_{task_name}_"))
    work = work_root / task_name
    shutil.copytree(src, work, ignore=shutil.ignore_patterns(".git", ".minicoder", "__pycache__"))
    _init_git(work)

    baseline_ok, _ = pytest_ok(work)
    snaps = snapshot_test_files(work)

    sm = StateManager(work / ".minicoder" / "state.db")
    await sm.initialize()

    preset = COMPRESSION_PRESETS[compression]
    usage: dict[str, Any] = {
        "prompt": 0,
        "completion": 0,
        "calls": 0,
        "compressions": 0,
    }
    status = "crash"
    msg = ""
    agent: CodingAgent | None = None
    steps = 0
    fell_back = False
    true_multi = False
    plan_source = ""
    worker_stats: list[dict[str, Any]] = []
    file_conflicts: list[dict[str, Any]] = []
    t0 = time.time()
    try:
        agent = CodingAgent(
            work,
            sm,
            api_key=api_key,
            base_url=base_url,
            model=model,
            max_steps=max_steps,
            mode=agent_mode,
            max_parallel=max_parallel,
            request_timeout=request_timeout,
            max_retries=max_retries,
            protect_tests=protect_tests,
        )
        agent.context.max_tokens = preset["max_tokens"]
        agent.context.keep_recent = preset["keep_recent"]
        if use_mock:
            from minicoder.mock_llm import MockOpenAI, MockResponse, MockToolCall

            agent.client = MockOpenAI(
                [
                    MockResponse(
                        tool_calls=[
                            MockToolCall(
                                id="finish",
                                function_name="finish",
                                arguments=json.dumps({"message": "mock eval noop"}),
                            )
                        ]
                    )
                ]
            )
        usage = _wrap_client_usage(agent)
        result = await agent.run(DEFAULT_TASK)
        status, msg = result["status"], result.get("message", "")
        steps = agent.current_step
        fell_back = bool(
            result.get("fell_back_to_single")
            or getattr(agent, "_fell_back_to_single", False)
        )
        true_multi = bool(result.get("true_multi") or getattr(agent, "_true_multi", False))
        plan_source = str(result.get("plan_source") or getattr(agent, "_plan_source", "") or "")
        worker_stats = list(
            result.get("worker_stats") or getattr(agent, "_worker_stats", []) or []
        )
        file_conflicts = list(result.get("file_conflicts") or [])
        if not file_conflicts:
            locks = getattr(agent, "_file_locks", None)
            if locks is not None:
                file_conflicts = list(locks.conflicts)
    except Exception as exc:
        status, msg = "crash", f"{type(exc).__name__}: {exc}"
        steps = 0
    wall = time.time() - t0
    await sm.close()

    restore_test_files(work, snaps)
    ok, summ = pytest_ok(work)

    flagged: list[str] = []
    if agent is not None:
        flagged = list(agent.test_guard.flagged)

    shutil.rmtree(work_root, ignore_errors=True)

    return RunRecord(
        config=compression,
        task=task_name,
        model=model,
        repeat=repeat,
        agent_mode=agent_mode,
        baseline_tests_pass=baseline_ok,
        tests_pass=ok,
        tests_restored=True,
        agent_status=status,
        agent_message=msg or "",
        steps=steps,
        llm_calls=int(usage.get("calls") or 0),
        prompt_tokens=int(usage.get("prompt") or 0),
        completion_tokens=int(usage.get("completion") or 0),
        total_tokens=int(usage.get("prompt") or 0) + int(usage.get("completion") or 0),
        compressions_triggered=int(usage.get("compressions") or 0),
        wall_s=round(wall, 1),
        pytest_summary=summ,
        test_files_flagged=flagged,
        error=None if status != "crash" else msg,
        fell_back_to_single=fell_back,
        true_multi=true_multi,
        plan_source=plan_source,
        worker_stats=worker_stats,
        file_conflicts=file_conflicts,
    )


def _mean_spread(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 3),
        "stdev": round(stdev, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def aggregate(records: list[RunRecord]) -> dict[str, Any]:
    """Group records by model/config/agent_mode and compute mean + spread."""
    groups: dict[str, list[RunRecord]] = {}
    for rec in records:
        key = f"{rec.model} / {rec.config} / {rec.agent_mode}"
        groups.setdefault(key, []).append(rec)

    out: dict[str, Any] = {}
    for key, rows in groups.items():
        n = len(rows)
        passed = sum(1 for r in rows if r.tests_pass)
        finished = sum(1 for r in rows if r.agent_status == "success")
        true_multi = sum(1 for r in rows if r.true_multi)
        fell_back = sum(1 for r in rows if r.fell_back_to_single)
        out[key] = {
            "n": n,
            "tests_pass": f"{passed}/{n}",
            "tests_pass_rate": passed / n if n else 0.0,
            "agent_finish": f"{finished}/{n}",
            "true_multi": f"{true_multi}/{n}",
            "fell_back_to_single": f"{fell_back}/{n}",
            "steps": _mean_spread([float(r.steps) for r in rows]),
            "total_tokens": _mean_spread([float(r.total_tokens) for r in rows]),
            "wall_s": _mean_spread([r.wall_s for r in rows]),
            "compressions": _mean_spread([float(r.compressions_triggered) for r in rows]),
        }
    return out


def render_markdown(records: list[RunRecord], summary: dict[str, Any]) -> str:
    lines = [
        "# MiniCoder evaluation",
        "",
        "Grading = original pytest files restored, then `pytest` in the workdir.",
        "No claimed pass-rate is implied beyond the numbers in this file.",
        "",
        "## Per run",
        "",
        "| model | config | mode | task | repeat | tests pass | agent | multi | steps | tokens | compress | wall s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        if r.true_multi:
            multi_flag = "true-multi"
        elif r.fell_back_to_single:
            multi_flag = "fallback"
        else:
            multi_flag = r.agent_mode
        lines.append(
            f"| {r.model} | {r.config} | {r.agent_mode} | {r.task} | {r.repeat} | "
            f"{'PASS' if r.tests_pass else 'FAIL'} | {r.agent_status} | {multi_flag} | "
            f"{r.steps} | {r.total_tokens} | {r.compressions_triggered} | {r.wall_s} |"
        )
    lines += ["", "## Aggregates (mean ± stdev)", ""]
    for key, agg in summary.items():
        steps = agg["steps"]
        toks = agg["total_tokens"]
        wall = agg["wall_s"]
        lines.append(
            f"- **{key}**: tests {agg['tests_pass']} "
            f"(rate {agg['tests_pass_rate']:.2%}), "
            f"agent finish {agg['agent_finish']}, "
            f"true multi {agg.get('true_multi', 'n/a')}, "
            f"fallback {agg.get('fell_back_to_single', 'n/a')}, "
            f"steps {steps['mean']} ± {steps['stdev']}, "
            f"tokens {toks['mean']} ± {toks['stdev']}, "
            f"wall_s {wall['mean']} ± {wall['stdev']}"
        )
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MiniCoder toy-repo benchmarks against an OpenAI-compatible API."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EVAL_MODEL") or os.environ.get("OPENAI_MODEL"),
        help="Model id (EVAL_MODEL or OPENAI_MODEL env). Required unless --mock.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
        help="OpenAI-compatible base URL (EVAL_BASE_URL or OPENAI_BASE_URL).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"),
        help="API key (OPENAI_API_KEY or DASHSCOPE_API_KEY).",
    )
    parser.add_argument(
        "--compression",
        choices=sorted(COMPRESSION_PRESETS),
        default="default",
        help="Context compression preset (default/off/aggressive).",
    )
    parser.add_argument(
        "--agent-mode",
        choices=["single", "multi"],
        default="single",
        help="Single loop, or multi-agent (repo-aware LLM plan + concurrent scoped workers).",
    )
    parser.add_argument("--repeats", type=int, default=1, help="Repeats per task (for mean/spread).")
    parser.add_argument("--max-steps", type=int, default=15, help="Step cap per run (shared in multi).")
    parser.add_argument(
        "--protect-tests",
        choices=["off", "block", "flag"],
        default="block",
        help="Guard test-file edits during the run (grading always restores originals).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=float(os.environ.get("MINICODER_REQUEST_TIMEOUT", "120")),
        help="Per-request LLM timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.environ.get("MINICODER_MAX_RETRIES", "2")),
        help="LLM retries after the first attempt (exponential backoff).",
    )
    parser.add_argument("--max-parallel", type=int, default=3, help="Concurrent sub-agents in multi mode.")
    parser.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task names (default: all toy repos).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        help="Directory for results.json and results.md.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use a mock LLM that immediately finishes (smoke-test the harness).",
    )
    parser.add_argument("--list-tasks", action="store_true", help="Print task names and exit.")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    discovered = list_toy_tasks()
    if args.list_tasks:
        for t in discovered:
            print(t["name"])
        return 0

    if not args.mock and not args.model:
        print(
            "error: --model is required (or set EVAL_MODEL / OPENAI_MODEL). "
            "Do not assume gpt-4.",
            file=sys.stderr,
        )
        return 2

    wanted = {n.strip() for n in args.tasks.split(",")} if args.tasks else None
    tasks = [t for t in discovered if wanted is None or t["name"] in wanted]
    if wanted is not None:
        missing = wanted - {t["name"] for t in tasks}
        if missing:
            print(f"error: unknown tasks: {sorted(missing)}", file=sys.stderr)
            return 2
    if not tasks:
        print("error: no toy repos found", file=sys.stderr)
        return 2

    model = args.model or "mock"
    records: list[RunRecord] = []
    for task in tasks:
        for repeat in range(1, args.repeats + 1):
            rec = await run_one(
                task_name=task["name"],
                src=Path(task["path"]),
                model=model,
                base_url=args.base_url,
                api_key=args.api_key,
                compression=args.compression,
                agent_mode=args.agent_mode,
                max_steps=args.max_steps,
                protect_tests=args.protect_tests,
                request_timeout=args.request_timeout,
                max_retries=args.max_retries,
                max_parallel=args.max_parallel,
                use_mock=args.mock,
                repeat=repeat,
            )
            records.append(rec)
            print(
                json.dumps(
                    {
                        "config": rec.config,
                        "task": rec.task,
                        "repeat": rec.repeat,
                        "agent_status": rec.agent_status,
                        "tests_pass": rec.tests_pass,
                        "baseline_tests_pass": rec.baseline_tests_pass,
                        "steps": rec.steps,
                        "total_tokens": rec.total_tokens,
                        "wall_s": rec.wall_s,
                        "true_multi": rec.true_multi,
                        "fell_back_to_single": rec.fell_back_to_single,
                        "plan_source": rec.plan_source,
                    }
                ),
                flush=True,
            )

    summary = aggregate(records)
    payload = {
        "records": [asdict(r) for r in records],
        "summary": summary,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    md_path = args.output_dir / "results.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(records, summary), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
