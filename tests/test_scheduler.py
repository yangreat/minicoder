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


@pytest.mark.asyncio
async def test_transitive_blocking_does_not_hang() -> None:
    """A→B→C: if A fails, B and C must become BLOCKED and run_all must return."""
    scheduler = TaskScheduler(max_parallel=2)
    a = scheduler.add_task("a", max_retries=0)
    b = scheduler.add_task("b", dependencies=[a], max_retries=0)
    scheduler.add_task("c", dependencies=[b], max_retries=0)

    async def agent_func(_executor: object, task: Task) -> dict[str, str]:
        if task.description == "a":
            return {"status": "failed", "message": "boom"}
        return {"status": "success", "message": "ok"}

    await asyncio.wait_for(scheduler.run_all(None, agent_func), timeout=2)
    statuses = {t.description: t.status for t in scheduler.tasks.values()}
    assert statuses["a"] == TaskStatus.FAILED
    assert statuses["b"] == TaskStatus.BLOCKED
    assert statuses["c"] == TaskStatus.BLOCKED
    pending = [t for t in scheduler.tasks.values() if t.status == TaskStatus.PENDING]
    assert pending == []


@pytest.mark.asyncio
async def test_failed_subtask_is_retried() -> None:
    scheduler = TaskScheduler(max_parallel=1)
    scheduler.add_task("a", max_retries=1)
    calls = {"n": 0}

    async def agent_func(_executor: object, task: Task) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "failed", "message": "Max steps reached"}
        return {"status": "success", "message": "ok"}

    await scheduler.run_all(None, agent_func)
    assert calls["n"] == 2
    statuses = {t.description: t.status for t in scheduler.tasks.values()}
    assert statuses["a"] == TaskStatus.COMPLETED


def test_planner_is_pure_chain() -> None:
    chain = [
        {"description": "a"},
        {"description": "b", "depends_on": [0]},
        {"description": "c", "depends_on": [1]},
    ]
    assert Planner.is_pure_chain(chain)
    parallel = Planner.decompose_coding_task("Fix the bug")
    assert not Planner.is_pure_chain(parallel)
    scheduler = TaskScheduler()
    Planner.create_task_graph(chain, scheduler)
    assert Planner.is_pure_chain_tasks(list(scheduler.tasks.values()))


def test_planner_fix_template_has_parallel_roots() -> None:
    steps = Planner.decompose_coding_task("Fix the bug in calculator.py")
    roots = [s for s in steps if not s.get("depends_on")]
    assert len(roots) >= 2
    scheduler = TaskScheduler()
    ids = Planner.create_task_graph(steps, scheduler)
    assert len(ids) == len(steps)
    ready = scheduler.get_ready_tasks()
    assert len(ready) >= 2
