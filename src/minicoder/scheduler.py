"""Task scheduling with planning and parallel execution."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
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
    dependencies: Set[str] = field(default_factory=set)
    priority: int = 0
    result: Optional[Any] = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3


class TaskScheduler:
    """Schedule and execute tasks with dependencies."""

    def __init__(self, max_parallel: int = 3):
        self.max_parallel = max_parallel
        self.tasks: Dict[str, Task] = {}
        self._semaphore = asyncio.Semaphore(max_parallel)

    def add_task(
        self,
        description: str,
        dependencies: Optional[List[str]] = None,
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

    def get_ready_tasks(self) -> List[Task]:
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
    ) -> Optional[Any]:
        """Execute a single task."""
        task = self.tasks[task_id]

        async with self._semaphore:
            while task.retries <= task.max_retries:
                try:
                    task.status = TaskStatus.RUNNING
                    result = await agent_func(executor, task.description)
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                    return result

                except Exception as e:
                    task.retries += 1
                    if task.retries > task.max_retries:
                        task.status = TaskStatus.FAILED
                        task.error = str(e)
                        raise
                    else:
                        await asyncio.sleep(2**task.retries)

        return None

    async def run_all(self, executor: Any, agent_func: Any) -> Dict[str, Any]:
        """Run all tasks, respecting dependencies."""
        results = {}

        while True:
            ready_tasks = self.get_ready_tasks()

            if not ready_tasks:
                pending = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
                if not pending:
                    break

                blocked = [
                    t
                    for t in pending
                    if any(self.tasks[dep].status == TaskStatus.FAILED for dep in t.dependencies)
                ]
                for task in blocked:
                    task.status = TaskStatus.BLOCKED
                    task.error = "Dependency failed"

                if len(blocked) == len(pending):
                    break

                await asyncio.sleep(0.1)
                continue

            batch = ready_tasks[: self.max_parallel]
            task_futures = [self.execute_task(task.id, executor, agent_func) for task in batch]

            try:
                batch_results = await asyncio.gather(*task_futures, return_exceptions=True)
                for task, result in zip(batch, batch_results):
                    if not isinstance(result, Exception):
                        results[task.id] = result
            except Exception:
                pass

            await asyncio.sleep(0.1)

        return results

    def get_status_summary(self) -> Dict[str, int]:
        """Get summary of task statuses."""
        summary = {status.value: 0 for status in TaskStatus}
        for task in self.tasks.values():
            summary[task.status.value] += 1
        return summary

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self.tasks.get(task_id)


class Planner:
    """Decompose high-level tasks into subtasks."""

    @staticmethod
    def decompose_coding_task(task_description: str) -> List[Dict[str, Any]]:
        """Decompose a coding task into steps."""
        steps = []

        if "fix" in task_description.lower() or "bug" in task_description.lower():
            steps = [
                {"description": "Understand the bug by examining error messages and tests", "priority": 3},
                {"description": "Locate the buggy code", "priority": 2, "depends_on": [0]},
                {"description": "Fix the bug", "priority": 1, "depends_on": [1]},
                {"description": "Verify the fix by running tests", "priority": 0, "depends_on": [2]},
            ]
        elif "implement" in task_description.lower() or "add" in task_description.lower():
            steps = [
                {"description": "Plan the implementation approach", "priority": 3},
                {"description": "Implement the feature", "priority": 2, "depends_on": [0]},
                {"description": "Add tests for the feature", "priority": 1, "depends_on": [1]},
                {"description": "Verify implementation", "priority": 0, "depends_on": [1, 2]},
            ]
        else:
            steps = [
                {"description": "Analyze the task requirements", "priority": 2},
                {"description": "Execute the task", "priority": 1, "depends_on": [0]},
                {"description": "Verify completion", "priority": 0, "depends_on": [1]},
            ]

        return steps

    @staticmethod
    def create_task_graph(steps: List[Dict[str, Any]], scheduler: TaskScheduler) -> List[str]:
        """Create a task graph from decomposed steps."""
        task_ids = []

        for step in steps:
            depends_on = step.get("depends_on", [])
            dep_ids = [task_ids[idx] for idx in depends_on if idx < len(task_ids)]

            task_id = scheduler.add_task(
                description=step["description"],
                dependencies=dep_ids,
                priority=step.get("priority", 0),
            )
            task_ids.append(task_id)

        return task_ids
