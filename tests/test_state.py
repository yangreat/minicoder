"""Test state management."""

import pytest
from pathlib import Path

from minicoder.state import AgentState, EventType, StateManager


@pytest.mark.asyncio
async def test_create_run(tmp_path: Path) -> None:
    """Test creating a run."""
    db_path = tmp_path / "test.db"
    manager = StateManager(db_path)
    await manager.initialize()

    try:
        run = await manager.create_run("test-run", "Test task", "/tmp/repo")

        assert run.run_id == "test-run"
        assert run.task == "Test task"
        assert run.state == AgentState.PLANNING
        assert run.total_steps == 0

        retrieved = await manager.get_run("test-run")
        assert retrieved is not None
        assert retrieved.run_id == "test-run"

    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_update_state(tmp_path: Path) -> None:
    """Test updating run state."""
    db_path = tmp_path / "test.db"
    manager = StateManager(db_path)
    await manager.initialize()

    try:
        await manager.create_run("test-run", "Test task", "/tmp/repo")
        await manager.update_run_state("test-run", AgentState.EXECUTING)

        run = await manager.get_run("test-run")
        assert run is not None
        assert run.state == AgentState.EXECUTING

    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_events(tmp_path: Path) -> None:
    """Test event logging."""
    db_path = tmp_path / "test.db"
    manager = StateManager(db_path)
    await manager.initialize()

    try:
        await manager.create_run("test-run", "Test task", "/tmp/repo")

        event = await manager.add_event(
            "test-run", EventType.MESSAGE_ADDED, {"role": "user", "content": "Hello"}
        )

        assert event.run_id == "test-run"
        assert event.event_type == EventType.MESSAGE_ADDED

        events = await manager.get_events("test-run")
        assert len(events) >= 1

        message_events = [e for e in events if e.event_type == EventType.MESSAGE_ADDED]
        assert len(message_events) == 1

    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_list_runs(tmp_path: Path) -> None:
    """Test listing runs."""
    db_path = tmp_path / "test.db"
    manager = StateManager(db_path)
    await manager.initialize()

    try:
        await manager.create_run("run-1", "Task 1", "/tmp/repo")
        await manager.create_run("run-2", "Task 2", "/tmp/repo")

        runs = await manager.list_runs()
        assert len(runs) == 2

        run_ids = [r.run_id for r in runs]
        assert "run-1" in run_ids
        assert "run-2" in run_ids

    finally:
        await manager.close()
