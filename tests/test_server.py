"""Tests for FastAPI server."""

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from minicoder.server import app
from minicoder.state import StateManager


client = TestClient(app)


def test_api_version():
    """Test API endpoint."""
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_runs_empty(tmp_path: Path):
    """Test listing runs when none exist."""
    response = client.get(f"/api/runs?repo_path={tmp_path}")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_start_run_mock(tmp_path: Path):
    """Test starting a run with mock LLM."""
    response = client.post(
        "/api/runs/start",
        json={
            "task": "Test task",
            "repo_path": str(tmp_path),
            "use_mock": True,
            "max_steps": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "started"


@pytest.mark.asyncio
async def test_get_run(tmp_path: Path):
    """Test getting run details."""
    db_path = tmp_path / ".minicoder" / "state.db"
    manager = StateManager(db_path)
    await manager.initialize()

    await manager.create_run("test-run", "Test task", str(tmp_path))

    response = client.get(f"/api/runs/test-run?repo_path={tmp_path}")
    assert response.status_code == 200

    data = response.json()
    assert data["run_id"] == "test-run"
    assert data["task"] == "Test task"

    await manager.close()


@pytest.mark.asyncio
async def test_get_run_events(tmp_path: Path):
    """Test getting run events."""
    db_path = tmp_path / ".minicoder" / "state.db"
    manager = StateManager(db_path)
    await manager.initialize()

    await manager.create_run("test-run", "Test task", str(tmp_path))

    response = client.get(f"/api/runs/test-run/events?repo_path={tmp_path}")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    await manager.close()


def test_get_nonexistent_run():
    """Test getting a run that doesn't exist."""
    response = client.get("/api/runs/nonexistent")
    assert response.status_code == 404
