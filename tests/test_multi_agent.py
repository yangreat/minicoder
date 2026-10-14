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


def _plan_response(subtasks: list[dict[object, object]], call_id: str = "plan") -> MockResponse:
    return MockResponse(
        tool_calls=[
            MockToolCall(
                id=call_id,
                function_name="emit_plan",
                arguments=json.dumps({"subtasks": subtasks}),
            )
        ]
    )


def _is_planner_call(kwargs: object) -> bool:
    messages = []
    if isinstance(kwargs, dict):
        messages = kwargs.get("messages") or []
    blob = "\n".join(m.get("content") or "" for m in messages)
    return "MiniCoder's planner" in blob or "emit_plan" in blob


def _write(path: str, content: str, call_id: str = "w") -> MockResponse:
    return MockResponse(
        tool_calls=[
            MockToolCall(
                id=call_id,
                function_name="write_file",
                arguments=json.dumps({"path": path, "content": content}),
            )
        ]
    )


def _seed_two_bug_repo(root: Path) -> None:
    (root / "pricing.py").write_text("def apply_discount(price, pct):\n    return 0\n")
    (root / "shipping.py").write_text("def shipping_cost(weight_kg):\n    return 0\n")
    (root / "test_pricing.py").write_text(
        "from pricing import apply_discount\n"
        "def test_discount():\n    assert apply_discount(200, 25) == 150.0\n"
    )
    (root / "test_shipping.py").write_text(
        "from shipping import shipping_cost\n"
        "def test_light():\n    assert shipping_cost(1) == 5.0\n"
    )
    (root / "README.md").write_text("two independent bugs\n")


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
            result = await asyncio.wait_for(agent.run("Fix the bug"), timeout=15)
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
                agent.run("Fix the bug in this repository"), timeout=15
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
async def test_llm_planner_two_scoped_edits_run_in_parallel(tmp_path: Path) -> None:
    _seed_two_bug_repo(tmp_path)
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        plan = [
            {
                "id": "pricing",
                "description": "Fix apply_discount in pricing.py",
                "kind": "edit",
                "files": ["pricing.py"],
                "failing_tests": ["test_pricing.py"],
            },
            {
                "id": "shipping",
                "description": "Fix shipping_cost in shipping.py",
                "kind": "edit",
                "files": ["shipping.py"],
                "failing_tests": ["test_shipping.py"],
            },
        ]
        mock = MockOpenAI(_finish_responses(30))
        orig = mock.chat.completions.create
        in_flight = 0
        max_flight = 0
        lock = asyncio.Lock()
        worker_blobs: list[str] = []

        async def create(**kwargs: object) -> MockResponse:
            nonlocal in_flight, max_flight
            if _is_planner_call(kwargs):
                return _plan_response(plan)
            blob = _user_blob(kwargs)
            worker_blobs.append(blob)
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
        result = await agent.run("Fix the bugs in this repository")
        assert result["status"] == "success"
        assert result["true_multi"] is True
        assert result["fell_back_to_single"] is False
        assert result["plan_source"] == "llm"
        assert max_flight >= 2
        pricing_blobs = [b for b in worker_blobs if "Fix apply_discount" in b]
        shipping_blobs = [b for b in worker_blobs if "Fix shipping_cost" in b]
        assert pricing_blobs
        assert shipping_blobs
        assert any("File in your scope: pricing.py" in b for b in pricing_blobs)
        assert not any("File in your scope: shipping.py" in b for b in pricing_blobs)
        assert any("File in your scope: shipping.py" in b for b in shipping_blobs)
        worker_descs = {w["description"] for w in result["worker_stats"] if w["kind"] == "edit"}
        assert "Fix apply_discount in pricing.py" in worker_descs
        assert "Fix shipping_cost in shipping.py" in worker_descs
        assert all("steps" in w and "tokens" in w for w in result["worker_stats"])
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_llm_plan_one_edit_falls_back_to_single(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        mock = MockOpenAI(_finish_responses(10))
        orig = mock.chat.completions.create

        async def create(**kwargs: object) -> MockResponse:
            if _is_planner_call(kwargs):
                return _plan_response(
                    [
                        {
                            "description": "Fix the only bug",
                            "kind": "edit",
                            "files": ["app.py"],
                        }
                    ]
                )
            return await orig(**kwargs)

        mock.chat.completions.create = create  # type: ignore[method-assign]
        agent = CodingAgent(tmp_path, sm, max_steps=8, mode="multi")
        agent.client = mock
        result = await agent.run("Fix the bug")
        assert result["status"] == "success"
        assert result["fell_back_to_single"] is True
        assert result["true_multi"] is False
        assert result["plan_source"] == "llm"
        user_blobs = [_user_blob(call) for call in mock.chat.completions.calls]
        assert not any("Your subtask" in blob for blob in user_blobs)
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_invalid_plan_json_uses_keyword_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        mock = MockOpenAI(_finish_responses(10))
        orig = mock.chat.completions.create

        async def create(**kwargs: object) -> MockResponse:
            if _is_planner_call(kwargs):
                return MockResponse(content="{this is not json")
            return await orig(**kwargs)

        mock.chat.completions.create = create  # type: ignore[method-assign]
        agent = CodingAgent(tmp_path, sm, max_steps=8, mode="multi")
        agent.client = mock
        result = await agent.run("Fix the bug")
        assert result["status"] == "success"
        assert result["plan_source"] == "keyword"
        assert result["fell_back_to_single"] is True
        assert "LLM plan invalid" in (agent._plan_error or "")
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_file_conflict_serialized_and_recorded(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        (tmp_path / "shared.py").write_text("old\n")
        writes: dict[str, int] = {"a": 0, "b": 0}
        mock = MockOpenAI([])
        in_flight = 0
        max_flight = 0
        lock = asyncio.Lock()

        async def create(**kwargs: object) -> MockResponse:
            nonlocal in_flight, max_flight
            if _is_planner_call(kwargs):
                return _plan_response(
                    [
                        {
                            "id": "a",
                            "description": "Worker A edits shared.py",
                            "kind": "edit",
                            "files": ["shared.py"],
                        },
                        {
                            "id": "b",
                            "description": "Worker B edits shared.py",
                            "kind": "edit",
                            "files": ["shared.py"],
                        },
                    ]
                )
            blob = _user_blob(kwargs)
            worker = "a" if "Worker A" in blob else "b"
            async with lock:
                in_flight += 1
                max_flight = max(max_flight, in_flight)
            try:
                await asyncio.sleep(0.08)
                if writes[worker] == 0:
                    writes[worker] += 1
                    return _write("shared.py", worker + "\n", call_id=f"{worker}-w")
                return _finish(f"done-{worker}", call_id=f"{worker}-f")
            finally:
                async with lock:
                    in_flight -= 1

        mock.chat.completions.create = create  # type: ignore[method-assign]
        agent = CodingAgent(tmp_path, sm, max_steps=16, mode="multi", max_parallel=3)
        agent.client = mock
        result = await asyncio.wait_for(
            agent.run("Fix two workers on the same file"), timeout=8
        )
        assert result["status"] == "success"
        assert result["true_multi"] is True
        assert (tmp_path / "shared.py").exists()
        assert result["file_conflicts"] or agent._file_locks.conflicts
        assert max_flight >= 2
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
