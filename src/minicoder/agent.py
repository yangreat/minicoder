"""Core coding agent with LLM integration."""

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
from minicoder.scheduler import Planner, Task, TaskScheduler, TaskStatus
from minicoder.state import AgentState, EventType, StateManager
from minicoder.tools import get_all_tools


class CodingAgent:
    """Main coding agent with LLM and tools."""

    def __init__(
        self,
        repo_path: Path,
        state_manager: StateManager,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4",
        max_steps: int = 30,
        use_docker: bool = False,
        step_delay: float = 0.0,
    ):
        self.repo_path = Path(repo_path)
        self.state_manager = state_manager
        self.model = model
        self.max_steps = max_steps
        self.step_delay = step_delay

        self.client: Any = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY", "dummy-key"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
        )

        self.context = ContextManager(self.repo_path, model=model)
        self.checkpoint = CheckpointManager(self.repo_path)
        self.tools = get_all_tools(self.repo_path, use_docker=use_docker)

        self.run_id: str | None = None
        self.current_step = 0
        self._plan_tasks: list[Task] = []
        self._plan_cursor = 0

    def _require_run_id(self) -> str:
        if not self.run_id:
            raise RuntimeError("Agent run_id is not set")
        return self.run_id

    async def run(self, task: str, run_id: str | None = None) -> dict[str, Any]:
        """Run the agent on a task."""
        self.run_id = run_id or str(uuid4())
        self.current_step = 0
        rid = self._require_run_id()

        existing = await self.state_manager.get_run(rid)
        if not existing:
            await self.state_manager.create_run(
                rid, task, str(self.repo_path), AgentState.PLANNING
            )
        else:
            await self.state_manager.update_run_state(rid, AgentState.PLANNING)

        await self._emit_plan(task)
        self.checkpoint.create_checkpoint(rid, 0, "baseline", allow_empty=True)
        await self.state_manager.add_event(
            rid,
            EventType.CHECKPOINT_CREATED,
            {"sha": self.checkpoint.get_current_sha(), "message": "baseline"},
        )

        system_prompt = self.context.get_system_prompt()
        self.context.add_message("system", system_prompt)
        self.context.add_message("user", task)

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

        events = await self.state_manager.get_events(run_id)
        await self._restore_context_from_events(events)

        result = await self._agent_loop()

        return {
            "run_id": self.run_id,
            "status": result["status"],
            "steps": self.current_step,
            "message": result.get("message", ""),
        }

    async def _emit_plan(self, task: str) -> None:
        """Decompose the task and emit DAG events."""
        rid = self._require_run_id()
        scheduler = TaskScheduler()
        steps = Planner.decompose_coding_task(task)
        # Keep the graph small and visual: 3 dependent subtasks.
        if len(steps) > 3:
            steps = steps[:3]
            if "depends_on" in steps[-1]:
                steps[-1]["depends_on"] = [len(steps) - 2]
        task_ids = Planner.create_task_graph(steps, scheduler)
        self._plan_tasks = []
        for tid in task_ids:
            planned = scheduler.get_task(tid)
            if planned is not None:
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
                    }
                },
            )
            if self.step_delay:
                await asyncio.sleep(self.step_delay / 2)

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
            {"task_id": task.id, "new_status": status.value},
        )

    async def _agent_loop(self) -> dict[str, Any]:
        """Main agent execution loop."""
        rid = self._require_run_id()
        while self.current_step < self.max_steps:
            try:
                await self.state_manager.update_run_state(rid, AgentState.EXECUTING)
                await self.state_manager.increment_steps(rid)
                self.current_step += 1

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
                        "tool_calls": (
                            [tc.model_dump() for tc in message.tool_calls]
                            if message.tool_calls
                            else None
                        ),
                    },
                )

                if message.tool_calls:
                    await self.state_manager.update_run_state(rid, AgentState.WAITING_TOOL)

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
                            {"tool_call_id": tool_call.id, "result": result},
                        )

                        self.context.add_tool_result(tool_call.id, json.dumps(result))

                        if result.get("name") == "finish":
                            for i in range(len(self._plan_tasks)):
                                await self._set_plan_status(i, TaskStatus.COMPLETED)
                            await self.state_manager.update_run_state(rid, AgentState.DONE)
                            return {
                                "status": "success",
                                "message": result.get("output", "Task completed"),
                            }

                    sha = self.checkpoint.create_checkpoint(
                        rid, self.current_step, "After tool execution"
                    )
                    await self.state_manager.add_event(
                        rid, EventType.CHECKPOINT_CREATED, {"sha": sha}
                    )
                    await self._set_plan_status(self._plan_cursor, TaskStatus.COMPLETED)
                    self._plan_cursor = min(self._plan_cursor + 1, max(len(self._plan_tasks) - 1, 0))

                elif message.content:
                    self.context.add_message("assistant", message.content)

                if response.usage:
                    await self.state_manager.add_token_usage(rid, response.usage.total_tokens)

            except Exception as e:
                await self.state_manager.add_event(
                    rid, EventType.ERROR, {"error": str(e), "step": self.current_step}
                )
                await self.state_manager.update_run_state(rid, AgentState.FAILED)
                return {"status": "failed", "message": str(e)}

        await self.state_manager.update_run_state(rid, AgentState.FAILED)
        return {"status": "failed", "message": f"Max steps ({self.max_steps}) reached"}

    async def _call_llm(self) -> Any:
        """Call the LLM with current context."""
        messages = self.context.get_messages()
        tools = self._get_tool_schemas()

        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, tool_choice="auto"
        )

        return response

    async def _execute_tool(self, tool_call: Any) -> dict[str, Any]:
        """Execute a tool call."""
        rid = self._require_run_id()
        function_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        await self.state_manager.add_event(
            rid,
            EventType.TOOL_CALLED,
            {"tool": function_name, "arguments": arguments, "call_id": tool_call.id},
        )

        if function_name == "finish":
            return {"name": "finish", "output": arguments.get("message", "Done")}

        for tool in self.tools:
            if tool.name == function_name:
                result = await tool.execute(**arguments)
                return {
                    "name": function_name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                }

        return {"name": function_name, "success": False, "error": f"Unknown tool: {function_name}"}

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
                self.context.add_tool_result(data["tool_call_id"], json.dumps(data["result"]))
