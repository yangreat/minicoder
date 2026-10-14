"""Task scheduling with planning and parallel execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable
from uuid import uuid4


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """A task in the execution plan."""

    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    dependencies: set[str] = field(default_factory=set)
    priority: int = 0
    result: Any | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 3
    agent_id: str | None = None


StatusCallback = Callable[[Task], Awaitable[None] | None]


class TaskScheduler:
    """Schedule and execute tasks with dependencies."""

    def __init__(self, max_parallel: int = 3, on_status: StatusCallback | None = None):
        self.max_parallel = max_parallel
        self.tasks: dict[str, Task] = {}
        self._semaphore = asyncio.Semaphore(max_parallel)
        self.on_status = on_status

    async def _set_status(self, task: Task, status: TaskStatus) -> None:
        if task.status == status:
            return
        task.status = status
        if self.on_status is not None:
            maybe = self.on_status(task)
            if asyncio.iscoroutine(maybe):
                await maybe

    def add_task(
        self,
        description: str,
        dependencies: list[str] | None = None,
        priority: int = 0,
        max_retries: int = 3,
    ) -> str:
        """Add a task to the scheduler."""
        task = Task(
            description=description,
            dependencies=set(dependencies or []),
            priority=priority,
            max_retries=max_retries,
        )
        self.tasks[task.id] = task
        return task.id

    def get_ready_tasks(self) -> list[Task]:
        """Get tasks that are ready to run."""
        ready = []

        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            deps_satisfied = all(
                self.tasks[dep_id].status == TaskStatus.COMPLETED for dep_id in task.dependencies
            )

            if deps_satisfied:
                ready.append(task)

        return sorted(ready, key=lambda t: -t.priority)

    async def execute_task(
        self, task_id: str, executor: Any, agent_func: Any
    ) -> Any | None:
        """Execute a single task."""
        task = self.tasks[task_id]

        async with self._semaphore:
            while task.retries <= task.max_retries:
                try:
                    await self._set_status(task, TaskStatus.RUNNING)
                    result = await agent_func(executor, task)
                    if isinstance(result, dict) and result.get("status") == "failed":
                        task.result = result
                        task.error = str(result.get("message", "failed"))
                        await self._set_status(task, TaskStatus.FAILED)
                        return result
                    await self._set_status(task, TaskStatus.COMPLETED)
                    task.result = result
                    return result

                except Exception as e:
                    task.retries += 1
                    if task.retries > task.max_retries:
                        await self._set_status(task, TaskStatus.FAILED)
                        task.error = str(e)
                        raise
                    else:
                        await self._set_status(task, TaskStatus.PENDING)
                        await asyncio.sleep(2**task.retries)

        return None

    async def run_all(self, executor: Any, agent_func: Any) -> dict[str, Any]:
        """Run all tasks, respecting dependencies.

        Independent ready tasks are launched concurrently (up to
        ``max_parallel``) via ``asyncio.gather``.
        """
        results: dict[str, Any] = {}

        while True:
            ready_tasks = self.get_ready_tasks()

            if not ready_tasks:
                pending = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
                running = [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]
                if running:
                    await asyncio.sleep(0.05)
                    continue
                if not pending:
                    break

                blocked = [
                    t
                    for t in pending
                    if any(
                        dep in self.tasks and self.tasks[dep].status == TaskStatus.FAILED
                        for dep in t.dependencies
                    )
                ]
                for task in blocked:
                    await self._set_status(task, TaskStatus.BLOCKED)
                    task.error = "Dependency failed"

                if len(blocked) == len(pending):
                    break

                await asyncio.sleep(0.05)
                continue

            batch = ready_tasks[: self.max_parallel]
            task_futures = [self.execute_task(task.id, executor, agent_func) for task in batch]

            batch_results = await asyncio.gather(*task_futures, return_exceptions=True)
            for task, result in zip(batch, batch_results):
                if not isinstance(result, Exception):
                    results[task.id] = result

        return results

    def get_status_summary(self) -> dict[str, int]:
        """Get summary of task statuses."""
        summary = {status.value: 0 for status in TaskStatus}
        for task in self.tasks.values():
            summary[task.status.value] += 1
        return summary

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self.tasks.get(task_id)


class Planner:
    """Decompose high-level tasks into subtasks with dependencies."""

    @staticmethod
    def decompose_coding_task(task_description: str) -> list[dict[str, Any]]:
        """Decompose a coding task into steps.

        Templates include at least one pair of independent subtasks so the
        scheduler can run them concurrently in multi-agent mode.
        """
        text = task_description.lower()

        if "fix" in text or "bug" in text:
            return [
                {"description": "Read README and project context", "priority": 3},
                {"description": "Read failing tests", "priority": 3},
                {
                    "description": "Locate the buggy code",
                    "priority": 2,
                    "depends_on": [0, 1],
                },
                {"description": "Apply the fix", "priority": 1, "depends_on": [2]},
                {
                    "description": "Verify the fix by running tests",
                    "priority": 0,
                    "depends_on": [3],
                },
            ]
        if "implement" in text or "add " in text:
            return [
                {"description": "Plan the implementation approach", "priority": 3},
                {
                    "description": "Implement the feature",
                    "priority": 2,
                    "depends_on": [0],
                },
                {
                    "description": "Add tests for the feature",
                    "priority": 2,
                    "depends_on": [0],
                },
                {
                    "description": "Verify implementation",
                    "priority": 0,
                    "depends_on": [1, 2],
                },
            ]
        return [
            {"description": "Analyze the task requirements", "priority": 2},
            {"description": "Gather relevant context", "priority": 2},
            {
                "description": "Execute the task",
                "priority": 1,
                "depends_on": [0, 1],
            },
            {"description": "Verify completion", "priority": 0, "depends_on": [2]},
        ]

    @staticmethod
    def create_task_graph(
        steps: list[dict[str, Any]],
        scheduler: TaskScheduler,
        max_retries: int = 0,
    ) -> list[str]:
        """Create a task graph from decomposed steps."""
        task_ids: list[str] = []

        for step in steps:
            depends_on = step.get("depends_on", [])
            dep_ids = [task_ids[idx] for idx in depends_on if idx < len(task_ids)]

            task_id = scheduler.add_task(
                description=step["description"],
                dependencies=dep_ids,
                priority=step.get("priority", 0),
                max_retries=step.get("max_retries", max_retries),
            )
            task_ids.append(task_id)

        return task_ids
