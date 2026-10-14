"""Multi-agent mode: planner DAG, concurrent sub-agents, isolated context."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from minicoder.agent import CodingAgent
from minicoder.mock_llm import MockOpenAI, MockResponse, MockToolCall
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


@pytest.mark.asyncio
async def test_multi_agent_emits_plan_and_merges(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=20, mode="multi", max_parallel=3)
        agent.client = MockOpenAI(_finish_responses(20))
        result = await agent.run("Fix the bug in this repository")
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
        result = await agent.run("Fix the bug")
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
        await agent.run("Fix the bug in the repo")
        user_blobs = []
        for call in mock.chat.completions.calls:
            messages = call.get("messages") or []
            user_blobs.append(
                "\n".join(m.get("content") or "" for m in messages if m.get("role") == "user")
            )
        # Distinct subtask descriptions land in distinct isolated contexts.
        assert any("Read README" in blob for blob in user_blobs)
        assert any("Read failing tests" in blob for blob in user_blobs)
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
        result = await agent.run("Fix the bug")
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
async def test_per_subtask_budgets_do_not_starve_later_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(tmp_path, sm, max_steps=8, mode="multi")
        seen: list[int] = []
        orig = agent._spawn_subagent

        def spawn(task: object, budget: int):  # type: ignore[no-untyped-def]
            seen.append(budget)
            return orig(task, budget)  # type: ignore[arg-type]

        agent._spawn_subagent = spawn  # type: ignore[method-assign]
        agent.client = MockOpenAI(_finish_responses(20))
        result = await agent.run("Fix the bug")
        assert result["status"] == "success"
        assert seen, "sub-agents must be spawned with budgets"
        assert all(b >= 1 for b in seen)
        assert min(seen) >= 1
        # Later workers (deps) should get a share, not zero leftover.
        assert max(seen) >= min(seen)
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_failed_subtasks_reported_and_finish_still_called(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        # Content-only mock: sub-agents never call finish, hit per-task caps.
        agent = CodingAgent(tmp_path, sm, max_steps=4, mode="multi", max_parallel=2)
        agent.client = MockOpenAI([])
        result = await asyncio.wait_for(agent.run("Fix the bug"), timeout=5)
        assert result["status"] == "failed"
        assert "Merged sub-agent results" in result["message"]
        events = await sm.get_events(result["run_id"])
        assert any(
            e.event_type == EventType.TOOL_CALLED
            and e.data.get("tool") == "finish"
            and e.data.get("agent_id") == "parent"
            for e in events
        )
        changed = [e for e in events if e.event_type == EventType.TASK_STATUS_CHANGED]
        assert any(e.data.get("new_status") == "failed" for e in changed)
        assert any(e.data.get("new_status") == "blocked" for e in changed)
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_pure_chain_falls_back_to_single(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        from minicoder.scheduler import Planner

        orig = Planner.decompose_coding_task
        Planner.decompose_coding_task = staticmethod(  # type: ignore[method-assign]
            lambda _task: [
                {"description": "Step A"},
                {"description": "Step B", "depends_on": [0]},
                {"description": "Step C", "depends_on": [1]},
            ]
        )
        try:
            agent = CodingAgent(tmp_path, sm, max_steps=5, mode="multi")
            agent.client = MockOpenAI(_finish_responses(3))
            result = await agent.run("Do the chain")
            assert result["status"] == "success"
            assert agent._fell_back_to_single is True
            user_blobs = []
            for call in agent.client.chat.completions.calls:
                messages = call.get("messages") or []
                user_blobs.append(
                    "\n".join(
                        m.get("content") or ""
                        for m in messages
                        if m.get("role") == "user"
                    )
                )
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
