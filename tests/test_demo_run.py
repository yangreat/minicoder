"""Demo-mode run: planner events, file edit, diff, and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from minicoder.agent import CodingAgent
from minicoder.checkpoint import CheckpointManager
from minicoder.demo import ORIGINAL_CALCULATOR, build_demo_client, restore_toy_calculator
from minicoder.server import app
from minicoder.state import EventType, StateManager

client = TestClient(app)


@pytest.fixture
def calc_repo(tmp_path: Path) -> Path:
    calc = tmp_path / "calculator"
    calc.mkdir()
    (calc / "calculator.py").write_text(ORIGINAL_CALCULATOR)
    return calc


@pytest.mark.asyncio
async def test_demo_agent_edits_and_rollback(calc_repo: Path) -> None:
    db_path = calc_repo / ".minicoder" / "state.db"
    manager = StateManager(db_path)
    await manager.initialize()
    try:
        agent = CodingAgent(calc_repo, manager, max_steps=10, step_delay=0)
        agent.client = build_demo_client(calc_repo)
        result = await agent.run("Fix the divide-by-zero bug in calculator.py")
        assert result["status"] == "success"

        events = await manager.get_events(result["run_id"])
        types = [e.event_type for e in events]
        assert EventType.TASK_CREATED in types
        assert EventType.TASK_STATUS_CHANGED in types
        assert EventType.TOOL_CALLED in types
        assert EventType.CHECKPOINT_CREATED in types

        created = [e for e in events if e.event_type == EventType.TASK_CREATED]
        assert len(created) >= 2
        assert created[1].data["subtask"]["dependencies"]

        source = (calc_repo / "calculator.py").read_text()
        assert "Cannot divide by zero" in source

        ckpt = CheckpointManager(calc_repo)
        diff = ckpt.get_run_diff(result["run_id"])
        assert "Cannot divide by zero" in diff

        checkpoints = ckpt.list_checkpoints(result["run_id"])
        assert len(checkpoints) >= 2
        baseline = checkpoints[-1]["full_sha"]
        ckpt.rollback(baseline)
        restored = (calc_repo / "calculator.py").read_text()
        assert "Cannot divide by zero" not in restored
        assert "return a / b" in restored
    finally:
        await manager.close()


def test_demo_start_via_api(calc_repo: Path) -> None:
    response = client.post(
        "/api/runs/start",
        json={
            "task": "Fix the bug in calculator.py",
            "repo_path": str(calc_repo),
            "use_mock": True,
            "max_steps": 10,
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    repo_path = response.json()["repo_path"]

    run = client.get(f"/api/runs/{run_id}?repo_path={repo_path}")
    assert run.status_code == 200
    assert run.json()["state"] in {"done", "executing", "planning", "waiting_tool"}

    events = client.get(f"/api/runs/{run_id}/events?repo_path={repo_path}")
    assert events.status_code == 200
    payload = events.json()
    assert any(e["event_type"] == "task_created" for e in payload)
    assert any(e["event_type"] == "tool_called" for e in payload)

    diff = client.get(f"/api/runs/{run_id}/diff?repo_path={repo_path}")
    assert diff.status_code == 200
    assert "Cannot divide by zero" in diff.json()["diff"]

    checkpoints = client.get(f"/api/runs/{run_id}/checkpoints?repo_path={repo_path}")
    assert checkpoints.status_code == 200
    cps = checkpoints.json()
    assert len(cps) >= 2
    baseline = cps[-1]["full_sha"]
    rb = client.post(
        f"/api/runs/{run_id}/rollback?repo_path={repo_path}",
        json={"checkpoint_sha": baseline},
    )
    assert rb.status_code == 200
    assert "Cannot divide by zero" not in (calc_repo / "calculator.py").read_text()


def test_restore_helper() -> None:
    restore_toy_calculator()
    toy = Path("benchmarks/toy_repos/calculator/calculator.py")
    if toy.exists():
        assert "Cannot divide by zero" not in toy.read_text()
