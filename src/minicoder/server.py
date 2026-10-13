"""FastAPI server for MiniCoder web console."""

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from minicoder.agent import CodingAgent
from minicoder.checkpoint import CheckpointManager
from minicoder.state import AgentState, EventType, RunMetadata, StateManager


app = FastAPI(title="MiniCoder API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRunRequest(BaseModel):
    """Request to start a new run."""

    task: str
    repo_path: str = "."
    model: str = "gpt-4"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    max_steps: int = 30
    use_docker: bool = False
    use_mock: bool = False


class ResumeRunRequest(BaseModel):
    """Request to resume a run."""

    run_id: str
    model: str = "gpt-4"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    max_steps: int = 30
    use_mock: bool = False


class RollbackRequest(BaseModel):
    """Request to rollback to a checkpoint."""

    checkpoint_sha: str


class RunResponse(BaseModel):
    """Response containing run information."""

    run_id: str
    task: str
    repo_path: str
    state: str
    created_at: float
    updated_at: float
    total_steps: int
    token_usage: int


class EventResponse(BaseModel):
    """Response containing an event."""

    id: str
    run_id: str
    timestamp: float
    event_type: str
    data: Dict[str, Any]


class CheckpointResponse(BaseModel):
    """Response containing checkpoint information."""

    sha: str
    full_sha: str
    message: str
    timestamp: str


class DiffResponse(BaseModel):
    """Response containing file diff."""

    diff: str


active_agents: Dict[str, CodingAgent] = {}
state_managers: Dict[str, StateManager] = {}


def get_state_manager(repo_path: str) -> StateManager:
    """Get or create state manager for a repo."""
    if repo_path not in state_managers:
        db_path = Path(repo_path) / ".minicoder" / "state.db"
        manager = StateManager(db_path)
        state_managers[repo_path] = manager
    return state_managers[repo_path]


async def ensure_state_manager_initialized(manager: StateManager) -> None:
    """Ensure state manager is initialized."""
    try:
        await manager.get_run("test")
    except Exception:
        await manager.initialize()


@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint."""
    return {"message": "MiniCoder API", "version": "0.1.0"}


@app.get("/api/runs", response_model=List[RunResponse])
async def list_runs(repo_path: str = ".", limit: int = 50) -> List[RunResponse]:
    """List all runs for a repository."""
    manager = get_state_manager(repo_path)
    await ensure_state_manager_initialized(manager)

    runs = await manager.list_runs(limit)
    return [
        RunResponse(
            run_id=run.run_id,
            task=run.task,
            repo_path=run.repo_path,
            state=run.state.value,
            created_at=run.created_at,
            updated_at=run.updated_at,
            total_steps=run.total_steps,
            token_usage=run.token_usage,
        )
        for run in runs
    ]


@app.get("/api/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, repo_path: str = ".") -> RunResponse:
    """Get details of a specific run."""
    manager = get_state_manager(repo_path)
    await ensure_state_manager_initialized(manager)

    run = await manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunResponse(
        run_id=run.run_id,
        task=run.task,
        repo_path=run.repo_path,
        state=run.state.value,
        created_at=run.created_at,
        updated_at=run.updated_at,
        total_steps=run.total_steps,
        token_usage=run.token_usage,
    )


@app.get("/api/runs/{run_id}/events", response_model=List[EventResponse])
async def get_run_events(run_id: str, repo_path: str = ".", limit: Optional[int] = None) -> List[EventResponse]:
    """Get events for a specific run."""
    manager = get_state_manager(repo_path)
    await ensure_state_manager_initialized(manager)

    events = await manager.get_events(run_id, limit)
    return [
        EventResponse(
            id=event.id,
            run_id=event.run_id,
            timestamp=event.timestamp,
            event_type=event.event_type.value,
            data=event.data,
        )
        for event in events
    ]


async def run_agent_with_stream(
    agent: CodingAgent,
    task: str,
    run_id: Optional[str] = None,
    resume: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    """Run agent and stream events."""
    try:
        if resume:
            result = await agent.resume(run_id)
        else:
            result = await agent.run(task, run_id)

        yield {
            "event": "run_complete",
            "data": result,
        }
    except Exception as e:
        yield {
            "event": "run_error",
            "data": {"error": str(e)},
        }


@app.post("/api/runs/start")
async def start_run(request: StartRunRequest, background_tasks: BackgroundTasks) -> Dict[str, str]:
    """Start a new run."""
    run_id = str(uuid4())
    repo_path = Path(request.repo_path).resolve()

    manager = get_state_manager(str(repo_path))
    await ensure_state_manager_initialized(manager)

    if request.use_mock:
        from tests.mock_llm import MockOpenAI, MockResponse, MockToolCall

        responses = [
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_demo",
                        function_name="finish",
                        arguments=json.dumps({"message": "Demo mode - task acknowledged"}),
                    )
                ]
            )
        ]
        mock_client = MockOpenAI(responses)

        agent = CodingAgent(
            repo_path,
            manager,
            model=request.model,
            max_steps=request.max_steps,
            use_docker=request.use_docker,
        )
        agent.client = mock_client
    else:
        agent = CodingAgent(
            repo_path,
            manager,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            max_steps=request.max_steps,
            use_docker=request.use_docker,
        )

    active_agents[run_id] = agent

    async def run_in_background() -> None:
        """Run agent in background."""
        try:
            await agent.run(request.task, run_id)
        finally:
            active_agents.pop(run_id, None)

    background_tasks.add_task(run_in_background)

    return {"run_id": run_id, "status": "started"}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, repo_path: str = ".") -> EventSourceResponse:
    """Stream events from a running agent."""
    manager = get_state_manager(repo_path)
    await ensure_state_manager_initialized(manager)

    async def event_generator() -> AsyncIterator[Dict[str, Any]]:
        """Generate SSE events."""
        events = await manager.get_events(run_id)
        for event in events:
            yield {
                "event": "agent_event",
                "data": json.dumps({
                    "id": event.id,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp,
                    "event_type": event.event_type.value,
                    "data": event.data,
                }),
            }

        run = await manager.get_run(run_id)
        if run and run.state in [AgentState.DONE, AgentState.FAILED]:
            yield {
                "event": "run_complete",
                "data": json.dumps({"status": run.state.value}),
            }

    return EventSourceResponse(event_generator())


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, request: ResumeRunRequest, background_tasks: BackgroundTasks) -> Dict[str, str]:
    """Resume a run."""
    manager = get_state_manager(request.repo_path if hasattr(request, 'repo_path') else ".")
    await ensure_state_manager_initialized(manager)

    run = await manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    repo_path = Path(run.repo_path)

    if request.use_mock:
        from tests.mock_llm import MockOpenAI, MockResponse, MockToolCall

        responses = [
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_demo",
                        function_name="finish",
                        arguments=json.dumps({"message": "Demo mode - resumed"}),
                    )
                ]
            )
        ]
        mock_client = MockOpenAI(responses)

        agent = CodingAgent(
            repo_path,
            manager,
            model=request.model,
            max_steps=request.max_steps,
        )
        agent.client = mock_client
    else:
        agent = CodingAgent(
            repo_path,
            manager,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            max_steps=request.max_steps,
        )

    active_agents[run_id] = agent

    async def resume_in_background() -> None:
        """Resume agent in background."""
        try:
            await agent.resume(run_id)
        finally:
            active_agents.pop(run_id, None)

    background_tasks.add_task(resume_in_background)

    return {"run_id": run_id, "status": "resumed"}


@app.get("/api/runs/{run_id}/checkpoints", response_model=List[CheckpointResponse])
async def list_checkpoints(run_id: str, repo_path: str = ".") -> List[CheckpointResponse]:
    """List checkpoints for a run."""
    checkpoint_manager = CheckpointManager(Path(repo_path))
    checkpoints = checkpoint_manager.list_checkpoints(run_id)

    return [
        CheckpointResponse(
            sha=cp["sha"],
            full_sha=cp["full_sha"],
            message=cp["message"],
            timestamp=cp["timestamp"],
        )
        for cp in checkpoints
    ]


@app.post("/api/runs/{run_id}/rollback")
async def rollback_checkpoint(run_id: str, request: RollbackRequest, repo_path: str = ".") -> Dict[str, str]:
    """Rollback to a checkpoint."""
    checkpoint_manager = CheckpointManager(Path(repo_path))

    try:
        checkpoint_manager.rollback(request.checkpoint_sha)
        return {"status": "success", "checkpoint": request.checkpoint_sha}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/runs/{run_id}/diff", response_model=DiffResponse)
async def get_run_diff(run_id: str, repo_path: str = ".", from_sha: Optional[str] = None) -> DiffResponse:
    """Get diff for a run."""
    checkpoint_manager = CheckpointManager(Path(repo_path))

    try:
        diff = checkpoint_manager.get_diff(from_sha=from_sha)
        return DiffResponse(diff=diff)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/runs/{run_id}/abort")
async def abort_run(run_id: str) -> Dict[str, str]:
    """Abort a running agent."""
    if run_id in active_agents:
        active_agents.pop(run_id)
        return {"status": "aborted"}
    return {"status": "not_running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
