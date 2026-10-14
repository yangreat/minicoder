"""Tests for the asyncio task scheduler."""

import asyncio

import pytest

from minicoder.scheduler import Planner, Task, TaskScheduler, TaskStatus


@pytest.mark.asyncio
async def test_independent_tasks_run_concurrently() -> None:
    scheduler = TaskScheduler(max_parallel=2)
    scheduler.add_task("a", max_retries=0)
    scheduler.add_task("b", max_retries=0)

    in_flight = 0
    max_flight = 0
    lock = asyncio.Lock()

    async def agent_func(_executor: object, task: Task) -> str:
        nonlocal in_flight, max_flight
        async with lock:
            in_flight += 1
            max_flight = max(max_flight, in_flight)
        await asyncio.sleep(0.15)
        async with lock:
            in_flight -= 1
        return task.description

    results = await scheduler.run_all(None, agent_func)
    assert len(results) == 2
    assert max_flight == 2
    assert scheduler.get_status_summary()["completed"] == 2


@pytest.mark.asyncio
async def test_dependencies_block_until_ready() -> None:
    scheduler = TaskScheduler(max_parallel=2)
    a = scheduler.add_task("a", max_retries=0)
    scheduler.add_task("b", dependencies=[a], max_retries=0)
    order: list[str] = []

    async def agent_func(_executor: object, task: Task) -> str:
        order.append(task.description)
        return "ok"

    await scheduler.run_all(None, agent_func)
    assert order == ["a", "b"]


@pytest.mark.asyncio
async def test_failed_dependency_blocks_children() -> None:
    scheduler = TaskScheduler(max_parallel=2)
    a = scheduler.add_task("a", max_retries=0)
    scheduler.add_task("b", dependencies=[a], max_retries=0)

    async def agent_func(_executor: object, task: Task) -> dict[str, str]:
        if task.description == "a":
            return {"status": "failed", "message": "boom"}
        return {"status": "success", "message": "ok"}

    await scheduler.run_all(None, agent_func)
    statuses = {t.description: t.status for t in scheduler.tasks.values()}
    assert statuses["a"] == TaskStatus.FAILED
    assert statuses["b"] == TaskStatus.BLOCKED


def test_planner_fix_template_has_parallel_roots() -> None:
    steps = Planner.decompose_coding_task("Fix the bug in calculator.py")
    roots = [s for s in steps if not s.get("depends_on")]
    assert len(roots) >= 2
    scheduler = TaskScheduler()
    ids = Planner.create_task_graph(steps, scheduler)
    assert len(ids) == len(steps)
    ready = scheduler.get_ready_tasks()
    assert len(ready) >= 2
