"""Core coding agent with LLM integration and optional multi-agent mode."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from minicoder.checkpoint import CheckpointManager
from minicoder.context import ContextManager
from minicoder.llm import create_with_retry, default_backoff, default_max_retries, default_timeout
from minicoder.scheduler import Planner, Task, TaskScheduler, TaskStatus
from minicoder.state import AgentState, EventType, StateManager
from minicoder.tools import get_all_tools
from minicoder.tools.guard import TestFileGuard

MUTATING_TOOLS = {"write_file", "apply_patch", "run_shell"}


class StepCounter:
    """Shared step budget for a run (parent + sub-agents)."""

    def __init__(self, max_steps: int):
        self.max_steps = max_steps
        self.value = 0
        self._lock = asyncio.Lock()

    async def consume(self) -> int | None:
        """Return the new 1-based step number, or None if the budget is exhausted."""
        async with self._lock:
            if self.value >= self.max_steps:
                return None
            self.value += 1
            return self.value


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
        self._step_counter = StepCounter(max_steps)
        self._workspace_lock = asyncio.Lock()
        self._is_subagent = False
        self.agent_id = "main"

    def _require_run_id(self) -> str:
        if not self.run_id:
            raise RuntimeError("Agent run_id is not set")
        return self.run_id

    async def run(self, task: str, run_id: str | None = None) -> dict[str, Any]:
        """Run the agent on a task."""
        self.run_id = run_id or str(uuid4())
        self.current_step = 0
        self._step_counter = StepCounter(self.max_steps)
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

        if self.mode == "multi":
            result = await self._run_multi(task)
        else:
            result = await self._agent_loop()

        return {
            "run_id": rid,
            "status": result["status"],
            "steps": self.current_step,
            "message": result.get("message", ""),
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
        steps = Planner.decompose_coding_task(task)
        task_ids = Planner.create_task_graph(steps, scheduler)
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
                    }
                },
            )
            if self.step_delay:
                await asyncio.sleep(self.step_delay / 2)

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

    def _spawn_subagent(self, task: Task) -> CodingAgent:
        """Create a sub-agent with isolated context sharing repo, client, and budget."""
        sub = CodingAgent(
            self.repo_path,
            self.state_manager,
            api_key=self._api_key,
            base_url=self._base_url,
            model=self.model,
            max_steps=self.max_steps,
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
        sub._step_counter = self._step_counter
        sub._workspace_lock = self._workspace_lock
        sub.checkpoint = self.checkpoint
        sub.test_guard = self.test_guard
        sub.tools = self.tools
        return sub

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
            parts.append(f"### {dep.description}\nstatus={dep.status.value}\n{msg}")
        return "\n\n".join(parts)

    async def _run_multi(self, task: str) -> dict[str, Any]:
        """Run independent subtasks concurrently via isolated sub-agents."""
        rid = self._require_run_id()
        scheduler = self._scheduler
        if scheduler is None:
            return {"status": "failed", "message": "No plan was produced"}

        await self.state_manager.update_run_state(rid, AgentState.EXECUTING)

        async def agent_func(_executor: Any, planned: Task) -> dict[str, Any]:
            extra = self._dependency_context(scheduler, planned)
            sub = self._spawn_subagent(planned)
            return await sub.run_subtask(task, planned.description, extra)

        await scheduler.run_all(self, agent_func)
        self.current_step = self._step_counter.value

        parts: list[str] = []
        any_failed = False
        for planned in self._plan_tasks:
            if planned.status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
                any_failed = True
            result = planned.result if isinstance(planned.result, dict) else {}
            msg = result.get("message", planned.error or "")
            parts.append(f"- [{planned.status.value}] {planned.description}: {msg}")

        message = "Merged sub-agent results:\n" + "\n".join(parts)
        await self.state_manager.add_event(
            rid,
            EventType.MESSAGE_ADDED,
            {"role": "assistant", "content": message, "agent_id": "parent"},
        )

        if any_failed:
            await self.state_manager.update_run_state(rid, AgentState.FAILED)
            return {"status": "failed", "message": message}

        await self.state_manager.update_run_state(rid, AgentState.DONE)
        return {"status": "success", "message": message}

    async def _agent_loop(self) -> dict[str, Any]:
        """Main agent execution loop."""
        rid = self._require_run_id()
        while True:
            try:
                step = await self._step_counter.consume()
                if step is None:
                    if not self._is_subagent:
                        await self.state_manager.update_run_state(
                            rid, AgentState.FAILED
                        )
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
                    await self.state_manager.add_token_usage(
                        rid, response.usage.total_tokens
                    )

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
        """Execute a tool call."""
        rid = self._require_run_id()
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

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
                if function_name in MUTATING_TOOLS:
                    async with self._workspace_lock:
                        result = await tool.execute(**arguments)
                else:
                    result = await tool.execute(**arguments)
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
