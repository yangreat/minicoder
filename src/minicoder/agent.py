"""Core coding agent with LLM integration and optional multi-agent mode."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from minicoder.checkpoint import CheckpointManager
from minicoder.context import ContextManager
from minicoder.explore import ExplorationNotes, RepoExplorer
from minicoder.filelock import FileLockManager
from minicoder.llm import create_with_retry, default_backoff, default_max_retries, default_timeout
from minicoder.planner import (
    EMIT_PLAN_TOOL,
    InvalidPlanError,
    keyword_fallback_steps,
    parse_plan_from_tool_arguments,
    parse_plan_text,
    plan_to_steps,
    planner_user_prompt,
)
from minicoder.scheduler import Planner, Task, TaskScheduler, TaskStatus
from minicoder.state import AgentState, EventType, StateManager
from minicoder.tools import get_all_tools
from minicoder.tools.guard import TestFileGuard

MUTATING_TOOLS = {"write_file", "apply_patch", "run_shell"}


class StepTotals:
    """Run-wide LLM-step counter (not a cap)."""

    def __init__(self) -> None:
        self.value = 0
        self._lock = asyncio.Lock()

    async def add(self) -> int:
        async with self._lock:
            self.value += 1
            return self.value


class StepCounter:
    """Per-agent step budget, optionally recording into a shared total."""

    def __init__(self, max_steps: int, totals: StepTotals | None = None):
        self.max_steps = max_steps
        self.value = 0
        self._lock = asyncio.Lock()
        self.totals = totals

    async def consume(self) -> int | None:
        """Return the new 1-based local step number, or None if the budget is exhausted."""
        async with self._lock:
            if self.value >= self.max_steps:
                return None
            self.value += 1
            local = self.value
        if self.totals is not None:
            await self.totals.add()
        return local


class CodingAgent:
    """Main coding agent with LLM and tools."""

    def __init__(
        self,
        repo_path: Path,
        state_manager: StateManager,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_steps: int = 30,
        use_docker: bool = False,
        step_delay: float = 0.0,
        mode: str = "single",
        max_parallel: int = 3,
        request_timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        protect_tests: str = "off",
        test_patterns: list[str] | None = None,
    ):
        self.repo_path = Path(repo_path)
        self.state_manager = state_manager
        self.model = model or os.getenv("OPENAI_MODEL") or os.getenv("EVAL_MODEL") or "gpt-4"
        self.max_steps = max_steps
        self.step_delay = step_delay
        self.mode = mode if mode in ("single", "multi") else "single"
        self.max_parallel = max_parallel
        self.request_timeout = (
            default_timeout() if request_timeout is None else float(request_timeout)
        )
        self.max_retries = default_max_retries() if max_retries is None else int(max_retries)
        self.retry_backoff = default_backoff() if retry_backoff is None else float(retry_backoff)
        self.protect_tests_mode = protect_tests
        self.test_patterns = test_patterns
        self._api_key = api_key
        self._base_url = base_url

        self.client: Any = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY", "dummy-key"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            timeout=self.request_timeout,
            max_retries=0,
        )

        self.context = ContextManager(self.repo_path, model=self.model)
        self.checkpoint = CheckpointManager(self.repo_path)
        self.test_guard = TestFileGuard(mode=protect_tests, patterns=test_patterns)
        self.tools = get_all_tools(
            self.repo_path, use_docker=use_docker, test_guard=self.test_guard
        )
        self._use_docker = use_docker

        self.run_id: str | None = None
        self.current_step = 0
        self._plan_tasks: list[Task] = []
        self._plan_cursor = 0
        self._scheduler: TaskScheduler | None = None
        self._step_totals = StepTotals()
        self._step_counter = StepCounter(max_steps, totals=self._step_totals)
        self._workspace_lock = asyncio.Lock()
        self._file_locks = FileLockManager()
        self._is_subagent = False
        self.agent_id = "main"
        self._fell_back_to_single = False
        self._true_multi = False
        self._plan_source = "keyword"
        self._plan_error: str | None = None
        self._exploration: ExplorationNotes | None = None
        self._worker_stats: list[dict[str, Any]] = []
        self._tokens_used = 0
        self._allowed_files: list[str] | None = None

    def _require_run_id(self) -> str:
        if not self.run_id:
            raise RuntimeError("Agent run_id is not set")
        return self.run_id

    async def run(self, task: str, run_id: str | None = None) -> dict[str, Any]:
        """Run the agent on a task."""
        self.run_id = run_id or str(uuid4())
        self.current_step = 0
        self._fell_back_to_single = False
        self._true_multi = False
        self._plan_source = "keyword"
        self._plan_error = None
        self._worker_stats = []
        self._tokens_used = 0
        self._step_totals = StepTotals()
        self._step_counter = StepCounter(self.max_steps, totals=self._step_totals)
        rid = self._require_run_id()

        existing = await self.state_manager.get_run(rid)
        if not existing:
            await self.state_manager.create_run(
                rid, task, str(self.repo_path), AgentState.PLANNING
            )
        else:
            await self.state_manager.update_run_state(rid, AgentState.PLANNING)

        await self._emit_plan(task)
        async with self._workspace_lock:
            self.checkpoint.create_checkpoint(rid, 0, "baseline", allow_empty=True)
        await self.state_manager.add_event(
            rid,
            EventType.CHECKPOINT_CREATED,
            {"sha": self.checkpoint.get_current_sha(), "message": "baseline"},
        )

        system_prompt = self.context.get_system_prompt()
        self.context.add_message("system", system_prompt)
        self.context.add_message("user", task)

        if self.mode == "multi" and not Planner.should_fallback_to_single(
            self._plan_tasks
        ):
            self._true_multi = True
            result = await self._run_multi(task)
        else:
            if self.mode == "multi":
                self._fell_back_to_single = True
                self._true_multi = False
                reason = self._plan_error or (
                    "Plan has fewer than 2 independent edit subtasks "
                    "(or is a pure chain); falling back to single-agent mode."
                )
                await self.state_manager.add_event(
                    rid,
                    EventType.MESSAGE_ADDED,
                    {
                        "role": "system",
                        "content": reason,
                        "agent_id": "parent",
                    },
                )
            result = await self._agent_loop()

        return {
            "run_id": rid,
            "status": result["status"],
            "steps": self.current_step,
            "message": result.get("message", ""),
            "fell_back_to_single": self._fell_back_to_single,
            "true_multi": self._true_multi,
            "plan_source": self._plan_source,
            "worker_stats": list(self._worker_stats),
            "file_conflicts": list(self._file_locks.conflicts),
        }

    async def resume(self, run_id: str) -> dict[str, Any]:
        """Resume a previous run."""
        run = await self.state_manager.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        self.run_id = run_id
        self.current_step = run.total_steps
        self._step_counter.value = run.total_steps

        events = await self.state_manager.get_events(run_id)
        await self._restore_context_from_events(events)

        if self.mode == "multi" and self._scheduler is not None:
            result = await self._run_multi(run.task)
        else:
            result = await self._agent_loop()

        return {
            "run_id": self.run_id,
            "status": result["status"],
            "steps": self.current_step,
            "message": result.get("message", ""),
        }

    async def run_subtask(
        self, overall_task: str, description: str, extra_context: str = ""
    ) -> dict[str, Any]:
        """Run this agent as a sub-agent on one subtask (isolated context)."""
        system_prompt = self.context.get_system_prompt()
        self.context.add_message("system", system_prompt)
        user = (
            "You are a MiniCoder sub-agent working on one subtask of a larger job.\n\n"
            f"Overall task:\n{overall_task}\n\n"
            f"Your subtask:\n{description}\n"
        )
        if extra_context:
            user += f"\nContext from completed dependency subtasks:\n{extra_context}\n"
        user += (
            "\nFocus only on this subtask. Use tools as needed, then call finish "
            "when this subtask is done."
        )
        self.context.add_message("user", user)
        return await self._agent_loop()

    async def _emit_plan(self, task: str) -> None:
        """Decompose the task and emit DAG events."""
        rid = self._require_run_id()
        on_status = self._on_scheduler_status if self.mode == "multi" else None
        scheduler = TaskScheduler(max_parallel=self.max_parallel, on_status=on_status)
        if self.mode == "multi":
            steps, source = await self._build_multi_plan(task)
            self._plan_source = source
        else:
            steps = Planner.decompose_coding_task(task)
            self._plan_source = "keyword"
        retries = 1 if self.mode == "multi" else 0
        task_ids = Planner.create_task_graph(steps, scheduler, max_retries=retries)
        self._scheduler = scheduler
        self._plan_tasks = []
        for tid in task_ids:
            planned = scheduler.get_task(tid)
            if planned is not None:
                planned.agent_id = planned.id[:8]
                self._plan_tasks.append(planned)
        self._plan_cursor = 0

        for planned in self._plan_tasks:
            await self.state_manager.add_event(
                rid,
                EventType.TASK_CREATED,
                {
                    "subtask": {
                        "id": planned.id,
                        "description": planned.description,
                        "status": planned.status.value,
                        "priority": planned.priority,
                        "dependencies": list(planned.dependencies),
                        "agent_id": planned.agent_id,
                        "kind": planned.kind,
                        "files": list(planned.files),
                        "failing_tests": list(planned.failing_tests),
                    }
                },
            )
            if self.step_delay:
                await asyncio.sleep(self.step_delay / 2)

    async def _build_multi_plan(self, task: str) -> tuple[list[dict[str, Any]], str]:
        """Explore the repo, ask the LLM for a JSON plan, keyword-fallback last."""
        rid = self._require_run_id()
        explorer = RepoExplorer()
        self._exploration = explorer.explore(self.repo_path)
        await self.state_manager.add_event(
            rid,
            EventType.MESSAGE_ADDED,
            {
                "role": "system",
                "content": "Exploration notes:\n" + self._exploration.summary,
                "agent_id": "planner",
            },
        )
        try:
            steps = await self._llm_plan_steps(task, self._exploration.summary)
            n_edits = sum(1 for s in steps if (s.get("kind") or "edit") == "edit")
            await self.state_manager.add_event(
                rid,
                EventType.MESSAGE_ADDED,
                {
                    "role": "system",
                    "content": (
                        f"LLM planner produced {len(steps)} subtasks "
                        f"({n_edits} edit)."
                    ),
                    "agent_id": "planner",
                },
            )
            return steps, "llm"
        except Exception as exc:
            self._plan_error = f"LLM plan invalid ({exc}); using keyword planner fallback."
            await self.state_manager.add_event(
                rid,
                EventType.MESSAGE_ADDED,
                {
                    "role": "system",
                    "content": self._plan_error,
                    "agent_id": "planner",
                },
            )
            return keyword_fallback_steps(task), "keyword"

    async def _llm_plan_steps(self, task: str, exploration_summary: str) -> list[dict[str, Any]]:
        """One LLM call; response must be schema-valid plan JSON or emit_plan."""
        step = await self._step_counter.consume()
        if step is None:
            raise InvalidPlanError("step budget exhausted before planning")
        self.current_step = step
        await self.state_manager.increment_steps(self._require_run_id())

        messages = [
            {
                "role": "system",
                "content": "You are MiniCoder's planner. Output only a structured plan.",
            },
            {
                "role": "user",
                "content": planner_user_prompt(task, exploration_summary),
            },
        ]
        response = await create_with_retry(
            self.client,
            timeout=self.request_timeout,
            max_retries=self.max_retries,
            backoff=self.retry_backoff,
            model=self.model,
            messages=messages,
            tools=[EMIT_PLAN_TOOL],
            tool_choice="auto",
        )
        if getattr(response, "usage", None):
            tokens = int(response.usage.total_tokens or 0)
            self._tokens_used += tokens
            await self.state_manager.add_token_usage(self._require_run_id(), tokens)

        if not getattr(response, "choices", None):
            raise InvalidPlanError("planner LLM returned no choices")
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        for tool_call in tool_calls:
            name = getattr(getattr(tool_call, "function", None), "name", "")
            if name != "emit_plan":
                continue
            args = getattr(tool_call.function, "arguments", "") or "{}"
            return plan_to_steps(parse_plan_from_tool_arguments(args))
        content = getattr(message, "content", None) or ""
        return plan_to_steps(parse_plan_text(content))

    async def _on_scheduler_status(self, task: Task) -> None:
        rid = self.run_id
        if not rid:
            return
        await self.state_manager.add_event(
            rid,
            EventType.TASK_STATUS_CHANGED,
            {
                "task_id": task.id,
                "new_status": task.status.value,
                "agent_id": task.agent_id or task.id[:8],
                "description": task.description,
            },
        )

    async def _set_plan_status(self, index: int, status: TaskStatus) -> None:
        if index < 0 or index >= len(self._plan_tasks):
            return
        rid = self._require_run_id()
        task = self._plan_tasks[index]
        if task.status == status:
            return
        task.status = status
        await self.state_manager.add_event(
            rid,
            EventType.TASK_STATUS_CHANGED,
            {
                "task_id": task.id,
                "new_status": status.value,
                "agent_id": self.agent_id,
            },
        )

    def _allocate_subtask_budgets(self, n: int, pool: int | None = None) -> list[int]:
        """Split the run step cap by subtask kind: edits get most of the steps."""
        n = max(n, 1)
        total = pool if pool is not None else self.max_steps
        total = max(total, n)
        kinds = [t.kind or "edit" for t in self._plan_tasks] or ["edit"] * n
        weights = {"read": 1, "verify": 2, "edit": 5}
        wlist = [weights.get(k, 2) for k in kinds]
        total_w = sum(wlist) or 1
        budgets = [max(1, (total * w) // total_w) for w in wlist]

        def shrink_order() -> list[int]:
            order: list[int] = []
            for kind in ("read", "verify", "edit"):
                order.extend(i for i, k in enumerate(kinds) if k == kind)
            return order or list(range(n))

        while sum(budgets) > total:
            reduced = False
            for i in shrink_order():
                if budgets[i] > 1:
                    budgets[i] -= 1
                    reduced = True
                    break
            if not reduced:
                break
        remainder = max(0, total - sum(budgets))
        edit_idx = [i for i, k in enumerate(kinds) if k == "edit"] or list(range(n))
        e = 0
        while remainder > 0:
            budgets[edit_idx[e % len(edit_idx)]] += 1
            remainder -= 1
            e += 1
        return budgets

    def _spawn_subagent(self, task: Task, budget: int) -> CodingAgent:
        """Create a sub-agent with isolated context and its own step budget."""
        sub = CodingAgent(
            self.repo_path,
            self.state_manager,
            api_key=self._api_key,
            base_url=self._base_url,
            model=self.model,
            max_steps=budget,
            use_docker=self._use_docker,
            step_delay=self.step_delay,
            mode="single",
            request_timeout=self.request_timeout,
            max_retries=self.max_retries,
            retry_backoff=self.retry_backoff,
            protect_tests=self.protect_tests_mode,
            test_patterns=self.test_patterns,
        )
        sub.client = self.client
        sub.run_id = self.run_id
        sub._is_subagent = True
        sub.agent_id = task.agent_id or task.id[:8]
        sub._step_totals = self._step_totals
        sub._step_counter = StepCounter(budget, totals=self._step_totals)
        sub._workspace_lock = self._workspace_lock
        sub._file_locks = self._file_locks
        sub.checkpoint = self.checkpoint
        sub.test_guard = self.test_guard
        sub.tools = self.tools
        sub._exploration = self._exploration
        sub._allowed_files = list(task.files) if task.files else None
        return sub

    def _collect_partial_notes(self) -> str:
        """Summarize isolated context so an exhausted subtask is still useful."""
        blobs: list[str] = []
        for msg in self.context.messages[-8:]:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role in ("assistant", "tool") and content:
                blobs.append(content[:500])
        return "\n".join(blobs) if blobs else "(no tool output yet)"

    def _dependency_context(self, scheduler: TaskScheduler, task: Task) -> str:
        parts: list[str] = []
        for dep_id in task.dependencies:
            dep = scheduler.get_task(dep_id)
            if dep is None:
                continue
            result = dep.result
            if isinstance(result, dict):
                msg = result.get("message", "")
            else:
                msg = "" if result is None else str(result)
            note = " (optional; treat as hints, not requirements)" if dep.optional else ""
            parts.append(
                f"### {dep.description}{note}\nstatus={dep.status.value}\n{msg}"
            )
        return "\n\n".join(parts)

    def _read_repo_file(self, rel: str, limit: int = 2500) -> str:
        path = self.repo_path / rel
        if not path.exists() or not path.is_file():
            return f"(file not found: {rel})"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return f"(unreadable {rel}: {exc})"
        if len(text) > limit:
            return text[:limit] + "\n... (truncated)"
        return text

    def _scoped_worker_context(self, planned: Task) -> str:
        """Files + failing tests for this worker, plus shared exploration notes."""
        parts: list[str] = []
        notes = self._exploration
        if notes is not None:
            tree = notes.file_tree
            if len(tree) > 1500:
                tree = tree[:1500] + "\n... (truncated)"
            parts.append("## Shared exploration (file tree)\n" + tree)
            if planned.failing_tests:
                parts.append(
                    "## Failing tests for this subtask\n"
                    + notes.filter_failures(planned.failing_tests)
                )
            elif notes.failing_tests:
                parts.append(
                    "## Failing tests (full suite excerpt)\n"
                    + notes.test_output[:2000]
                )
        files = list(planned.files)
        if not files and notes is not None:
            files = list(notes.related_files.keys())
        seen: set[str] = set()
        for rel in files:
            if rel in seen:
                continue
            seen.add(rel)
            content = None
            if notes is not None:
                content = notes.related_files.get(rel)
            if not content:
                content = self._read_repo_file(rel)
            parts.append(f"## File in your scope: {rel}\n{content}")
        if planned.files:
            parts.append(
                "You should only edit these files: " + ", ".join(planned.files)
            )
        if planned.failing_tests:
            parts.append(
                "Your failing tests: " + ", ".join(planned.failing_tests)
            )
        return "\n\n".join(parts)

    def _record_worker_stat(self, planned: Task, sub: CodingAgent) -> None:
        planned.steps_used = sub.current_step
        planned.tokens_used = sub._tokens_used
        result = planned.result if isinstance(planned.result, dict) else {}
        self._worker_stats.append(
            {
                "agent_id": planned.agent_id or planned.id[:8],
                "description": planned.description,
                "kind": planned.kind,
                "status": planned.status.value,
                "steps": planned.steps_used,
                "tokens": planned.tokens_used,
                "files": list(planned.files),
                "failing_tests": list(planned.failing_tests),
                "partial": bool(result.get("partial")),
                "message": str(result.get("message") or planned.error or ""),
            }
        )

    def _run_full_suite(self) -> tuple[bool, str, int]:
        """Coordinator pytest over the whole repo (no LLM).

        Return ``(passed, output, returncode)``. Pytest uses 5 when no tests
        were collected; the coordinator then skips the repair pass.
        """
        try:
            env = os.environ.copy()
            env.pop("PYTEST_ADDOPTS", None)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        except Exception as exc:
            return False, f"pytest failed to start: {exc}", -1
        text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return (
            proc.returncode == 0,
            text[-4000:] if text else f"exit {proc.returncode}",
            int(proc.returncode),
        )

    async def _coordinator_finish(self, message: str, *, success: bool) -> dict[str, Any]:
        """Record a parent finish tool call after merging sub-agent results."""
        rid = self._require_run_id()
        await self.state_manager.add_event(
            rid,
            EventType.TOOL_CALLED,
            {
                "tool": "finish",
                "arguments": {"message": message},
                "call_id": "coordinator_finish",
                "agent_id": "parent",
            },
        )
        await self.state_manager.add_event(
            rid,
            EventType.TOOL_RESULT,
            {
                "tool_call_id": "coordinator_finish",
                "result": {"name": "finish", "output": message},
                "agent_id": "parent",
            },
        )
        if success:
            await self.state_manager.update_run_state(rid, AgentState.DONE)
            return {"status": "success", "message": message}
        await self.state_manager.update_run_state(rid, AgentState.FAILED)
        return {"status": "failed", "message": message}

    async def _run_multi(self, task: str) -> dict[str, Any]:
        """Run independent subtasks concurrently via isolated sub-agents."""
        rid = self._require_run_id()
        scheduler = self._scheduler
        if scheduler is None:
            return {"status": "failed", "message": "No plan was produced"}

        await self.state_manager.update_run_state(rid, AgentState.EXECUTING)
        remaining = max(1, self.max_steps - self._step_totals.value)
        budgets = self._allocate_subtask_budgets(len(self._plan_tasks), remaining)
        budget_by_id = {
            planned.id: budgets[i] for i, planned in enumerate(self._plan_tasks)
        }
        spawned: dict[str, CodingAgent] = {}

        async def agent_func(_executor: Any, planned: Task) -> dict[str, Any]:
            extra = self._scoped_worker_context(planned)
            dep_ctx = self._dependency_context(scheduler, planned)
            if dep_ctx:
                extra = extra + "\n\n## Context from completed dependency subtasks\n" + dep_ctx
            sub = self._spawn_subagent(planned, budget_by_id.get(planned.id, 3))
            spawned[planned.id] = sub
            result = await sub.run_subtask(task, planned.description, extra)
            return result

        try:
            await scheduler.run_all(self, agent_func)
        except Exception as exc:
            self.current_step = self._step_totals.value
            message = f"Scheduler error while running subtasks: {exc}"
            await self.state_manager.add_event(
                rid,
                EventType.MESSAGE_ADDED,
                {"role": "assistant", "content": message, "agent_id": "parent"},
            )
            return await self._coordinator_finish(message, success=False)

        self.current_step = self._step_totals.value
        self._worker_stats = []
        parts: list[str] = []
        hard_failed = False
        for planned in self._plan_tasks:
            sub = spawned.get(planned.id)
            if sub is not None:
                self._record_worker_stat(planned, sub)
            if planned.status in (TaskStatus.FAILED, TaskStatus.BLOCKED) and not planned.optional:
                hard_failed = True
            result = planned.result if isinstance(planned.result, dict) else {}
            msg = result.get("message", planned.error or "")
            tag = planned.status.value
            if result.get("partial"):
                tag = f"{tag}, partial"
            parts.append(f"- [{tag}] {planned.description}: {msg}")

        message = "Merged sub-agent results:\n" + "\n".join(parts)
        if self._file_locks.conflicts:
            message += "\n\nFile conflicts:\n" + json.dumps(self._file_locks.conflicts)
        await self.state_manager.add_event(
            rid,
            EventType.MESSAGE_ADDED,
            {"role": "assistant", "content": message, "agent_id": "parent"},
        )
        return await self._verify_and_repair(task, message, hard_failed)

    async def _verify_and_repair(
        self, overall_task: str, merge_message: str, hard_failed: bool
    ) -> dict[str, Any]:
        """Run the full suite; if it fails, one single-agent repair pass."""
        ok, output, code = self._run_full_suite()
        if ok:
            message = merge_message + "\n\nFull test suite: PASS\n" + output
            return await self._coordinator_finish(message, success=True)
        if code == 5 or "no tests ran" in output.lower():
            return await self._coordinator_finish(merge_message, success=not hard_failed)

        remaining = max(0, self.max_steps - self._step_totals.value)
        if remaining <= 0:
            message = (
                merge_message
                + "\n\nFull test suite: FAIL (no steps left for repair)\n"
                + output
            )
            return await self._coordinator_finish(message, success=not hard_failed)

        repair_task = Task(
            description="Repair remaining test failures after parallel workers",
            kind="edit",
            agent_id="repair",
        )
        extra = (
            merge_message
            + "\n\nThe combined patch did not make the full suite pass. "
            "Fix remaining failures. Do not revert unrelated worker edits.\n\n"
            f"Pytest output:\n{output}"
        )
        sub = self._spawn_subagent(repair_task, remaining)
        repair_result = await sub.run_subtask(
            overall_task,
            "Fix remaining failing tests so the full suite passes.",
            extra,
        )
        if isinstance(repair_result, dict) and repair_result.get("status") == "failed":
            repair_task.status = TaskStatus.FAILED
        else:
            repair_task.status = TaskStatus.COMPLETED
        repair_task.result = repair_result
        self.current_step = self._step_totals.value
        self._record_worker_stat(repair_task, sub)
        ok2, output2, _code2 = self._run_full_suite()
        repair_msg = ""
        if isinstance(repair_result, dict):
            repair_msg = str(repair_result.get("message") or "")
        status_line = "PASS" if ok2 else "FAIL"
        message = (
            merge_message
            + f"\n\nRepair pass ({repair_task.status.value}): {repair_msg}"
            + f"\n\nFull test suite after repair: {status_line}\n"
            + output2
        )
        success = ok2 or not hard_failed
        return await self._coordinator_finish(message, success=success)

    async def _agent_loop(self) -> dict[str, Any]:
        """Main agent execution loop."""
        rid = self._require_run_id()
        while True:
            try:
                step = await self._step_counter.consume()
                if step is None:
                    if self._is_subagent:
                        notes = self._collect_partial_notes()
                        return {
                            "status": "success",
                            "partial": True,
                            "message": (
                                f"Step budget ({self.max_steps}) exhausted; "
                                f"partial findings:\n{notes}"
                            ),
                        }
                    await self.state_manager.update_run_state(rid, AgentState.FAILED)
                    return {
                        "status": "failed",
                        "message": f"Max steps ({self.max_steps}) reached",
                    }
                self.current_step = step
                if not self._is_subagent:
                    await self.state_manager.update_run_state(rid, AgentState.EXECUTING)
                await self.state_manager.increment_steps(rid)

                if not self._is_subagent:
                    await self._set_plan_status(self._plan_cursor, TaskStatus.RUNNING)
                if self.step_delay:
                    await asyncio.sleep(self.step_delay)

                response = await self._call_llm()

                if not response.choices:
                    return {"status": "failed", "message": "No response from LLM"}

                message = response.choices[0].message

                await self.state_manager.add_event(
                    rid,
                    EventType.MESSAGE_ADDED,
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "agent_id": self.agent_id,
                        "tool_calls": (
                            [tc.model_dump() for tc in message.tool_calls]
                            if message.tool_calls
                            else None
                        ),
                    },
                )

                if message.tool_calls:
                    if not self._is_subagent:
                        await self.state_manager.update_run_state(
                            rid, AgentState.WAITING_TOOL
                        )

                    tool_calls_dicts = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]
                    self.context.add_message(
                        "assistant", message.content or "", tool_calls=tool_calls_dicts
                    )

                    for tool_call in message.tool_calls:
                        result = await self._execute_tool(tool_call)

                        await self.state_manager.add_event(
                            rid,
                            EventType.TOOL_RESULT,
                            {
                                "tool_call_id": tool_call.id,
                                "result": result,
                                "agent_id": self.agent_id,
                            },
                        )

                        self.context.add_tool_result(tool_call.id, json.dumps(result))

                        if result.get("name") == "finish":
                            if self._is_subagent:
                                return {
                                    "status": "success",
                                    "message": result.get("output", "Task completed"),
                                }
                            for i in range(len(self._plan_tasks)):
                                await self._set_plan_status(i, TaskStatus.COMPLETED)
                            await self.state_manager.update_run_state(
                                rid, AgentState.DONE
                            )
                            return {
                                "status": "success",
                                "message": result.get("output", "Task completed"),
                            }

                    async with self._workspace_lock:
                        sha = self.checkpoint.create_checkpoint(
                            rid, self.current_step, "After tool execution"
                        )
                    await self.state_manager.add_event(
                        rid,
                        EventType.CHECKPOINT_CREATED,
                        {"sha": sha, "agent_id": self.agent_id},
                    )
                    if not self._is_subagent:
                        await self._set_plan_status(
                            self._plan_cursor, TaskStatus.COMPLETED
                        )
                        self._plan_cursor = min(
                            self._plan_cursor + 1, max(len(self._plan_tasks) - 1, 0)
                        )

                elif message.content:
                    self.context.add_message("assistant", message.content)

                if response.usage:
                    tokens = int(response.usage.total_tokens or 0)
                    self._tokens_used += tokens
                    await self.state_manager.add_token_usage(rid, tokens)

            except Exception as e:
                await self.state_manager.add_event(
                    rid,
                    EventType.ERROR,
                    {
                        "error": str(e),
                        "step": self.current_step,
                        "agent_id": self.agent_id,
                    },
                )
                if not self._is_subagent:
                    await self.state_manager.update_run_state(rid, AgentState.FAILED)
                return {"status": "failed", "message": str(e)}

    async def _call_llm(self) -> Any:
        """Call the LLM with current context, timeout, and retries."""
        messages = self.context.get_messages()
        tools = self._get_tool_schemas()

        return await create_with_retry(
            self.client,
            timeout=self.request_timeout,
            max_retries=self.max_retries,
            backoff=self.retry_backoff,
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

    async def _execute_tool(self, tool_call: Any) -> dict[str, Any]:
        """Execute a tool call.

        Malformed JSON arguments are returned as a tool error so the model can retry
        instead of aborting the whole run.
        """
        rid = self._require_run_id()
        function_name = getattr(getattr(tool_call, "function", None), "name", "") or "unknown"
        raw_arguments = getattr(getattr(tool_call, "function", None), "arguments", "") or ""

        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
            if not isinstance(arguments, dict):
                raise json.JSONDecodeError(
                    "tool arguments must be a JSON object", raw_arguments, 0
                )
        except json.JSONDecodeError as exc:
            await self.state_manager.add_event(
                rid,
                EventType.TOOL_CALLED,
                {
                    "tool": function_name,
                    "arguments": raw_arguments,
                    "call_id": tool_call.id,
                    "agent_id": self.agent_id,
                    "error": "invalid_json",
                },
            )
            return {
                "name": function_name,
                "success": False,
                "output": "",
                "error": (
                    "Invalid JSON in tool arguments "
                    f"({exc}). Please retry the same tool with valid JSON."
                ),
            }

        await self.state_manager.add_event(
            rid,
            EventType.TOOL_CALLED,
            {
                "tool": function_name,
                "arguments": arguments,
                "call_id": tool_call.id,
                "agent_id": self.agent_id,
            },
        )

        if function_name == "finish":
            return {"name": "finish", "output": arguments.get("message", "Done")}

        for tool in self.tools:
            if tool.name == function_name:
                result = await self._run_tool(function_name, tool, arguments)
                return {
                    "name": function_name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                }

        return {
            "name": function_name,
            "success": False,
            "error": f"Unknown tool: {function_name}",
        }

    async def _run_tool(self, function_name: str, tool: Any, arguments: dict[str, Any]) -> Any:
        path = str(arguments.get("path") or "")
        if function_name in ("write_file", "apply_patch") and path:
            async with self._file_locks.hold(path, self.agent_id):
                return await tool.execute(**arguments)
        if function_name == "run_shell":
            async with self._workspace_lock:
                return await tool.execute(**arguments)
        return await tool.execute(**arguments)

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for LLM."""
        schemas = []

        for tool in self.tools:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )

        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Call this when the task is complete",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Summary of what was accomplished",
                            }
                        },
                        "required": ["message"],
                    },
                },
            }
        )

        return schemas

    async def _restore_context_from_events(self, events: list[Any]) -> None:
        """Restore context from event history."""
        for event in events:
            if event.event_type == EventType.MESSAGE_ADDED:
                data = event.data
                self.context.add_message(
                    data["role"], data["content"], data.get("tool_calls")
                )
            elif event.event_type == EventType.TOOL_RESULT:
                data = event.data
                self.context.add_tool_result(
                    data["tool_call_id"], json.dumps(data["result"])
                )
