"""Multi-agent mode: planner DAG, concurrent sub-agents, isolated context."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from minicoder.agent import CodingAgent
from minicoder.mock_llm import MockOpenAI, MockResponse, MockToolCall
from minicoder.scheduler import Planner, Task
from minicoder.state import EventType, StateManager


def _finish_responses(n: int) -> list[MockResponse]:
    return [
        MockResponse(
            tool_calls=[
                MockToolCall(
                    id=f"c{i}",
                    function_name="finish",
                    arguments=json.dumps({"message": f"done-{i}"}),
                )
            ]
        )
        for i in range(n)
    ]


def _finish(msg: str, call_id: str = "f") -> MockResponse:
    return MockResponse(
        tool_calls=[
            MockToolCall(
                id=call_id,
                function_name="finish",
                arguments=json.dumps({"message": msg}),
            )
        ]
    )


@contextmanager
def _force_multi() -> Iterator[None]:
    """Run the DAG even when the plan has fewer than 2 independent edits."""
    orig = Planner.should_fallback_to_single
    Planner.should_fallback_to_single = staticmethod(lambda _tasks: False)  # type: ignore[method-assign]
    try:
        yield
    finally:
        Planner.should_fallback_to_single = orig  # type: ignore[method-assign]


def _user_blob(kwargs: object) -> str:
    messages = []
    if isinstance(kwargs, dict):
        messages = kwargs.get("messages") or []
    return "\n".join(m.get("content") or "" for m in messages if m.get("role") == "user")


@pytest.mark.asyncio
async def test_multi_agent_emits_plan_and_merges(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=20, mode="multi", max_parallel=3)
        agent.client = MockOpenAI(_finish_responses(20))
        result = await agent.run("Implement the feature in this repository")
        assert result["status"] == "success"
        assert "Merged sub-agent results" in result["message"]

        events = await sm.get_events(result["run_id"])
        types = [e.event_type for e in events]
        assert types.count(EventType.TASK_CREATED) >= 4
        assert EventType.TASK_STATUS_CHANGED in types
        created = [e for e in events if e.event_type == EventType.TASK_CREATED]
        assert any(not e.data["subtask"]["dependencies"] for e in created)
        assert any(e.data["subtask"]["dependencies"] for e in created)
        changed = [e for e in events if e.event_type == EventType.TASK_STATUS_CHANGED]
        assert any(e.data.get("new_status") == "running" for e in changed)
        assert any(e.data.get("new_status") == "completed" for e in changed)
        assert any(e.data.get("agent_id") for e in changed)
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_multi_agent_runs_independent_subtasks_concurrently(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        mock = MockOpenAI(_finish_responses(20))
        orig = mock.chat.completions.create
        in_flight = 0
        max_flight = 0
        lock = asyncio.Lock()

        async def create(**kwargs: object) -> MockResponse:
            nonlocal in_flight, max_flight
            async with lock:
                in_flight += 1
                max_flight = max(max_flight, in_flight)
            try:
                await asyncio.sleep(0.12)
                return await orig(**kwargs)
            finally:
                async with lock:
                    in_flight -= 1

        mock.chat.completions.create = create  # type: ignore[method-assign]

        agent = CodingAgent(tmp_path, sm, max_steps=20, mode="multi", max_parallel=3)
        agent.client = mock
        result = await agent.run("Implement the feature")
        assert result["status"] == "success"
        assert max_flight >= 2
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_subagents_have_isolated_context(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        mock = MockOpenAI(_finish_responses(20))
        agent = CodingAgent(tmp_path, sm, max_steps=20, mode="multi")
        agent.client = mock
        await agent.run("Implement the feature in the repo")
        user_blobs = []
        for call in mock.chat.completions.calls:
            user_blobs.append(_user_blob(call))
        assert any("Implement the feature" in blob for blob in user_blobs)
        assert any("Add tests for the feature" in blob for blob in user_blobs)
        assert len(user_blobs) >= 2
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_coordinator_calls_finish_after_merge(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=16, mode="multi")
        agent.client = MockOpenAI(_finish_responses(20))
        result = await agent.run("Implement the feature")
        assert result["status"] == "success"
        events = await sm.get_events(result["run_id"])
        parent_finish = [
            e
            for e in events
            if e.event_type == EventType.TOOL_CALLED
            and e.data.get("tool") == "finish"
            and e.data.get("agent_id") == "parent"
        ]
        assert parent_finish, "coordinator must call finish after merging"
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_edit_subtasks_get_most_of_the_step_budget(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=15, mode="multi")
        seen: list[tuple[str, int]] = []
        orig = agent._spawn_subagent

        def spawn(task: Task, budget: int) -> CodingAgent:
            seen.append((task.description, budget))
            return orig(task, budget)

        agent._spawn_subagent = spawn  # type: ignore[method-assign]
        agent.client = MockOpenAI(_finish_responses(20))
        with _force_multi():
            result = await agent.run("Fix the bug")
        assert result["status"] == "success"
        by_desc = {desc: budget for desc, budget in seen}
        read_budgets = [b for d, b in seen if d.startswith("Read")]
        edit_budget = by_desc.get("Locate the buggy code and apply the fix", 0)
        assert read_budgets
        assert edit_budget > max(read_budgets)
        assert edit_budget >= sum(read_budgets)
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_exhausted_reads_do_not_fail_the_run(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=8, mode="multi", max_parallel=2)
        agent.client = MockOpenAI([])
        with _force_multi():
            result = await asyncio.wait_for(agent.run("Fix the bug"), timeout=5)
        events = await sm.get_events(result["run_id"])
        assert any(
            e.event_type == EventType.TOOL_CALLED
            and e.data.get("tool") == "finish"
            and e.data.get("agent_id") == "parent"
            for e in events
        )
        assert "Merged sub-agent results" in result["message"]
        assert "[blocked]" not in result["message"]
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_v3_plan_shape_fix_still_runs_when_reads_exhaust(tmp_path: Path) -> None:
    """Reproduce 425af4a: [read README] || [read tests] → locate+apply → verify.

    Reads never call finish (content-only, they burn their small budget). The
    locate+apply worker must still run instead of being BLOCKED.
    """
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        mock = MockOpenAI([])
        ran_fix = {"n": 0}

        async def create(**kwargs: object) -> MockResponse:
            blob = _user_blob(kwargs)
            if "Locate the buggy code and apply the fix" in blob:
                ran_fix["n"] += 1
                return _finish("patched", "fix")
            if "Verify the fix" in blob:
                return _finish("verified", "ver")
            return MockResponse(content="still reading files...")

        mock.chat.completions.create = create  # type: ignore[method-assign]
        agent = CodingAgent(tmp_path, sm, max_steps=15, mode="multi", max_parallel=3)
        agent.client = mock
        with _force_multi():
            result = await asyncio.wait_for(
                agent.run("Fix the bug in this repository"), timeout=8
            )
        assert ran_fix["n"] >= 1, "locate+apply subtask must still run"
        assert "Locate the buggy code and apply the fix" in result["message"]
        assert "[blocked] Locate" not in result["message"]
        events = await sm.get_events(result["run_id"])
        assert any(
            e.event_type == EventType.TOOL_CALLED
            and e.data.get("tool") == "finish"
            and e.data.get("agent_id") == "parent"
            for e in events
        )
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_fix_plan_falls_back_to_single(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=5, mode="multi")
        agent.client = MockOpenAI(_finish_responses(3))
        result = await agent.run("Fix the bug")
        assert result["status"] == "success"
        assert agent._fell_back_to_single is True
        user_blobs = [_user_blob(call) for call in agent.client.chat.completions.calls]
        assert not any("Your subtask" in blob for blob in user_blobs)
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_pure_chain_falls_back_to_single(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        orig = Planner.decompose_coding_task
        Planner.decompose_coding_task = staticmethod(  # type: ignore[method-assign]
            lambda _task: [
                {"description": "Step A", "kind": "edit"},
                {"description": "Step B", "kind": "edit", "depends_on": [0]},
                {"description": "Step C", "kind": "edit", "depends_on": [1]},
            ]
        )
        try:
            agent = CodingAgent(tmp_path, sm, max_steps=5, mode="multi")
            agent.client = MockOpenAI(_finish_responses(3))
            result = await agent.run("Do the chain")
            assert result["status"] == "success"
            assert agent._fell_back_to_single is True
            user_blobs = [_user_blob(call) for call in agent.client.chat.completions.calls]
            assert not any("Your subtask" in blob for blob in user_blobs)
        finally:
            Planner.decompose_coding_task = orig  # type: ignore[method-assign]
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_single_mode_still_works(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=5, mode="single")
        agent.client = MockOpenAI(_finish_responses(3))
        result = await agent.run("Fix the bug")
        assert result["status"] == "success"
    finally:
        await sm.close()
