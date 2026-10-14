"""Command-line interface for MiniCoder."""

import asyncio
import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from minicoder.agent import CodingAgent
from minicoder.checkpoint import CheckpointManager
from minicoder.state import StateManager

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """MiniCoder - A coding agent with task scheduling and state management."""
    pass


@main.command()
@click.argument("task")
@click.option("--repo", type=click.Path(exists=True), default=".", help="Repository path")
@click.option(
    "--model",
    default=lambda: os.getenv("OPENAI_MODEL") or os.getenv("EVAL_MODEL") or "gpt-4",
    help="LLM model to use (or OPENAI_MODEL / EVAL_MODEL env)",
)
@click.option("--base-url", default=None, help="OpenAI-compatible API base URL")
@click.option("--api-key", default=None, help="API key (or use OPENAI_API_KEY env var)")
@click.option("--max-steps", default=30, type=int, help="Maximum execution steps")
@click.option("--docker", is_flag=True, help="Use Docker sandbox for shell commands")
@click.option(
    "--mode",
    type=click.Choice(["single", "multi"]),
    default="single",
    help="single loop, or multi-agent (repo-aware LLM plan + concurrent scoped workers)",
)
@click.option("--max-parallel", default=3, type=int, help="Max concurrent sub-agents in multi mode")
@click.option("--request-timeout", default=None, type=float, help="LLM request timeout in seconds")
@click.option("--max-retries", default=None, type=int, help="LLM retries after the first attempt")
@click.option(
    "--protect-tests",
    type=click.Choice(["off", "block", "flag"]),
    default="off",
    help="Guard edits to test files",
)
def run(
    task: str,
    repo: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    max_steps: int,
    docker: bool,
    mode: str,
    max_parallel: int,
    request_timeout: float | None,
    max_retries: int | None,
    protect_tests: str,
) -> None:
    """Run the agent on a task."""
    asyncio.run(
        _run_agent(
            task,
            repo,
            model,
            base_url,
            api_key,
            max_steps,
            docker,
            mode,
            max_parallel,
            request_timeout,
            max_retries,
            protect_tests,
        )
    )


async def _run_agent(
    task: str,
    repo: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    max_steps: int,
    docker: bool,
    mode: str = "single",
    max_parallel: int = 3,
    request_timeout: float | None = None,
    max_retries: int | None = None,
    protect_tests: str = "off",
) -> None:
    """Async implementation of run command."""
    repo_path = Path(repo).resolve()
    db_path = repo_path / ".minicoder" / "state.db"

    console.print("[bold blue]Starting MiniCoder[/bold blue]")
    console.print(f"Task: {task}")
    console.print(f"Repo: {repo_path}")
    console.print(f"Model: {model}")

    state_manager = StateManager(db_path)
    await state_manager.initialize()

    try:
        agent = CodingAgent(
            repo_path,
            state_manager,
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            model=model,
            max_steps=max_steps,
            use_docker=docker,
            mode=mode,
            max_parallel=max_parallel,
            request_timeout=request_timeout,
            max_retries=max_retries,
            protect_tests=protect_tests,
        )

        result = await agent.run(task)

        console.print(f"\n[bold]Result:[/bold] {result['status']}")
        console.print(f"[bold]Run ID:[/bold] {result['run_id']}")
        console.print(f"[bold]Steps:[/bold] {result['steps']}")
        if result.get("message"):
            console.print(f"[bold]Message:[/bold] {result['message']}")

    finally:
        await state_manager.close()


@main.command()
@click.argument("run_id")
@click.option("--repo", type=click.Path(exists=True), default=".", help="Repository path")
@click.option(
    "--model",
    default=lambda: os.getenv("OPENAI_MODEL") or os.getenv("EVAL_MODEL") or "gpt-4",
    help="LLM model to use",
)
@click.option("--base-url", default=None, help="OpenAI-compatible API base URL")
@click.option("--api-key", default=None, help="API key")
@click.option("--max-steps", default=30, type=int, help="Maximum execution steps")
@click.option(
    "--mode",
    type=click.Choice(["single", "multi"]),
    default="single",
    help="single or multi agent",
)
def resume(
    run_id: str,
    repo: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    max_steps: int,
    mode: str,
) -> None:
    """Resume a previous run."""
    asyncio.run(_resume_agent(run_id, repo, model, base_url, api_key, max_steps, mode))


async def _resume_agent(
    run_id: str,
    repo: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    max_steps: int,
    mode: str = "single",
) -> None:
    """Async implementation of resume command."""
    repo_path = Path(repo).resolve()
    db_path = repo_path / ".minicoder" / "state.db"

    console.print(f"[bold blue]Resuming run {run_id}[/bold blue]")

    state_manager = StateManager(db_path)
    await state_manager.initialize()

    try:
        agent = CodingAgent(
            repo_path,
            state_manager,
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            model=model,
            max_steps=max_steps,
            mode=mode,
        )

        result = await agent.resume(run_id)

        console.print(f"\n[bold]Result:[/bold] {result['status']}")
        console.print(f"[bold]Steps:[/bold] {result['steps']}")
        if result.get("message"):
            console.print(f"[bold]Message:[/bold] {result['message']}")

    finally:
        await state_manager.close()


@main.command()
@click.option("--repo", type=click.Path(exists=True), default=".", help="Repository path")
@click.option("--limit", default=20, type=int, help="Maximum number of runs to show")
def runs(repo: str, limit: int) -> None:
    """List all runs."""
    asyncio.run(_list_runs(repo, limit))


async def _list_runs(repo: str, limit: int) -> None:
    """Async implementation of runs command."""
    repo_path = Path(repo).resolve()
    db_path = repo_path / ".minicoder" / "state.db"

    if not db_path.exists():
        console.print("[yellow]No runs found[/yellow]")
        return

    state_manager = StateManager(db_path)
    await state_manager.initialize()

    try:
        all_runs = await state_manager.list_runs(limit)

        if not all_runs:
            console.print("[yellow]No runs found[/yellow]")
            return

        table = Table(title="MiniCoder Runs")
        table.add_column("Run ID", style="cyan")
        table.add_column("State", style="magenta")
        table.add_column("Steps", justify="right", style="green")
        table.add_column("Tokens", justify="right", style="blue")
        table.add_column("Task", style="white")

        for run in all_runs:
            table.add_row(
                run.run_id[:8],
                run.state.value,
                str(run.total_steps),
                str(run.token_usage),
                run.task[:50] + "..." if len(run.task) > 50 else run.task,
            )

        console.print(table)

    finally:
        await state_manager.close()


@main.command()
@click.argument("run_id")
@click.argument("checkpoint_sha")
@click.option("--repo", type=click.Path(exists=True), default=".", help="Repository path")
def rollback(run_id: str, checkpoint_sha: str, repo: str) -> None:
    """Rollback to a checkpoint."""
    repo_path = Path(repo).resolve()

    console.print(f"[bold yellow]Rolling back to {checkpoint_sha}[/bold yellow]")

    try:
        checkpoint_manager = CheckpointManager(repo_path)
        checkpoint_manager.rollback(checkpoint_sha)
        console.print("[bold green]Rollback successful[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Rollback failed: {e}[/bold red]")


@main.command()
@click.argument("run_id")
@click.option("--repo", type=click.Path(exists=True), default=".", help="Repository path")
def checkpoints(run_id: str, repo: str) -> None:
    """List checkpoints for a run."""
    repo_path = Path(repo).resolve()
    checkpoint_manager = CheckpointManager(repo_path)

    checkpoints_list = checkpoint_manager.list_checkpoints(run_id)

    if not checkpoints_list:
        console.print("[yellow]No checkpoints found[/yellow]")
        return

    table = Table(title=f"Checkpoints for run {run_id}")
    table.add_column("SHA", style="cyan")
    table.add_column("Message", style="white")
    table.add_column("Timestamp", style="green")

    for checkpoint in checkpoints_list:
        table.add_row(checkpoint["sha"], checkpoint["message"], checkpoint["timestamp"])

    console.print(table)


@main.command()
@click.option("--host", default="0.0.0.0", help="Server host")
@click.option("--port", default=8000, type=int, help="Server port")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the web server."""
    import uvicorn

    console.print(f"[bold blue]Starting MiniCoder server on http://{host}:{port}[/bold blue]")

    uvicorn.run(
        "minicoder.server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
