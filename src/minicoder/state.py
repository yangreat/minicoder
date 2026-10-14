"""State management with event sourcing and SQLite persistence."""

import json
import time
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite
from pydantic import BaseModel, Field


class AgentState(str, Enum):
    """Agent lifecycle states."""

    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_TOOL = "waiting_tool"
    DONE = "done"
    FAILED = "failed"


class EventType(str, Enum):
    """Event types for event sourcing."""

    RUN_STARTED = "run_started"
    STATE_CHANGED = "state_changed"
    MESSAGE_ADDED = "message_added"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    CHECKPOINT_CREATED = "checkpoint_created"
    ERROR = "error"


class Event(BaseModel):
    """An event in the agent's history."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    timestamp: float = Field(default_factory=time.time)
    event_type: EventType
    data: dict[str, Any]


class RunMetadata(BaseModel):
    """Metadata about an agent run."""

    run_id: str
    task: str
    repo_path: str
    state: AgentState
    created_at: float
    updated_at: float
    total_steps: int = 0
    token_usage: int = 0


class StateManager:
    """Manages agent state with event sourcing."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)

        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                total_steps INTEGER DEFAULT 0,
                token_usage INTEGER DEFAULT 0
            )
            """
        )

        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                data TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
            """
        )

        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id, timestamp)"
        )

        await self._conn.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()

    async def create_run(
        self, run_id: str, task: str, repo_path: str, state: AgentState = AgentState.PLANNING
    ) -> RunMetadata:
        """Create a new run."""
        now = time.time()
        metadata = RunMetadata(
            run_id=run_id,
            task=task,
            repo_path=repo_path,
            state=state,
            created_at=now,
            updated_at=now,
        )

        await self._conn.execute(  # type: ignore
            """
            INSERT INTO runs (run_id, task, repo_path, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, task, repo_path, state.value, now, now),
        )
        await self._conn.commit()  # type: ignore

        await self.add_event(
            run_id, EventType.RUN_STARTED, {"task": task, "repo_path": repo_path}
        )

        return metadata

    async def get_run(self, run_id: str) -> RunMetadata | None:
        """Get run metadata."""
        async with self._conn.execute(  # type: ignore
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            return RunMetadata(
                run_id=row[0],
                task=row[1],
                repo_path=row[2],
                state=AgentState(row[3]),
                created_at=row[4],
                updated_at=row[5],
                total_steps=row[6],
                token_usage=row[7],
            )

    async def list_runs(self, limit: int = 50) -> list[RunMetadata]:
        """List all runs."""
        async with self._conn.execute(  # type: ignore
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                RunMetadata(
                    run_id=row[0],
                    task=row[1],
                    repo_path=row[2],
                    state=AgentState(row[3]),
                    created_at=row[4],
                    updated_at=row[5],
                    total_steps=row[6],
                    token_usage=row[7],
                )
                for row in rows
            ]

    async def update_run_state(self, run_id: str, state: AgentState) -> None:
        """Update run state."""
        await self._conn.execute(  # type: ignore
            "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
            (state.value, time.time(), run_id),
        )
        await self._conn.commit()  # type: ignore

        await self.add_event(run_id, EventType.STATE_CHANGED, {"new_state": state.value})

    async def increment_steps(self, run_id: str) -> None:
        """Increment step counter."""
        await self._conn.execute(  # type: ignore
            "UPDATE runs SET total_steps = total_steps + 1, updated_at = ? WHERE run_id = ?",
            (time.time(), run_id),
        )
        await self._conn.commit()  # type: ignore

    async def add_token_usage(self, run_id: str, tokens: int) -> None:
        """Add to token usage."""
        await self._conn.execute(  # type: ignore
            "UPDATE runs SET token_usage = token_usage + ?, updated_at = ? WHERE run_id = ?",
            (tokens, time.time(), run_id),
        )
        await self._conn.commit()  # type: ignore

    async def add_event(self, run_id: str, event_type: EventType, data: dict[str, Any]) -> Event:
        """Add an event to the history."""
        event = Event(run_id=run_id, event_type=event_type, data=data)

        await self._conn.execute(  # type: ignore
            """
            INSERT INTO events (id, run_id, timestamp, event_type, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event.id, run_id, event.timestamp, event_type.value, json.dumps(data)),
        )
        await self._conn.commit()  # type: ignore

        return event

    async def get_events(self, run_id: str, limit: int | None = None) -> list[Event]:
        """Get events for a run."""
        query = "SELECT * FROM events WHERE run_id = ? ORDER BY timestamp ASC"
        params: tuple = (run_id,)

        if limit:
            query += " LIMIT ?"
            params = (run_id, limit)

        async with self._conn.execute(query, params) as cursor:  # type: ignore
            rows = await cursor.fetchall()
            return [
                Event(
                    id=row[0],
                    run_id=row[1],
                    timestamp=row[2],
                    event_type=EventType(row[3]),
                    data=json.loads(row[4]),
                )
                for row in rows
            ]
