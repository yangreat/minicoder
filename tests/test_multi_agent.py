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
