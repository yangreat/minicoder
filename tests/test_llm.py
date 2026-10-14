"""Tests for LLM timeout and retry-with-backoff."""

import asyncio
from pathlib import Path

import pytest

from minicoder.agent import CodingAgent
from minicoder.llm import create_with_retry
from minicoder.mock_llm import MockResponse, MockToolCall
from minicoder.state import StateManager


class _FlakyCompletions:
    def __init__(self) -> None:
        self.n = 0

    async def create(self, **kwargs: object) -> MockResponse:
        self.n += 1
        if self.n < 3:
            raise ConnectionError("transient")
        return MockResponse(
            tool_calls=[
                MockToolCall(
                    id="c1",
                    function_name="finish",
                    arguments='{"message": "ok"}',
                )
            ]
        )


class _SlowCompletions:
    async def create(self, **kwargs: object) -> MockResponse:
        await asyncio.sleep(5)
        return MockResponse(content="late")


class _AuthBoom:
    def __init__(self) -> None:
        self.n = 0

    async def create(self, **kwargs: object) -> MockResponse:
        self.n += 1
        raise ValueError("invalid api key")


class _Client:
    def __init__(self, completions: object) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_retry_on_connection_error() -> None:
    flaky = _FlakyCompletions()
    client = _Client(flaky)
    result = await create_with_retry(
        client, timeout=5, max_retries=3, backoff=0.01, model="x", messages=[]
    )
    assert result.choices
    assert flaky.n == 3


@pytest.mark.asyncio
async def test_timeout_does_not_hang() -> None:
    client = _Client(_SlowCompletions())
    with pytest.raises(TimeoutError, match="failed after"):
        await create_with_retry(
            client, timeout=0.05, max_retries=1, backoff=0.01, model="x", messages=[]
        )


@pytest.mark.asyncio
async def test_non_retryable_errors_fail_immediately() -> None:
    boom = _AuthBoom()
    client = _Client(boom)
    with pytest.raises(ValueError, match="invalid api key"):
        await create_with_retry(
            client, timeout=5, max_retries=5, backoff=0.01, model="x", messages=[]
        )
    assert boom.n == 1


@pytest.mark.asyncio
async def test_agent_times_out_llm_call(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(
            tmp_path,
            sm,
            max_steps=3,
            request_timeout=0.05,
            max_retries=0,
            retry_backoff=0.01,
        )
        agent.client = _Client(_SlowCompletions())
        result = await agent.run("do something")
        assert result["status"] == "failed"
        assert "timeout" in result["message"].lower() or "Timeout" in result["message"]
    finally:
        await sm.close()


@pytest.mark.asyncio
async def test_agent_retries_then_succeeds(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    sm = StateManager(db_path)
    await sm.initialize()
    try:
        agent = CodingAgent(
            tmp_path,
            sm,
            max_steps=5,
            request_timeout=5,
            max_retries=4,
            retry_backoff=0.01,
        )
        agent.client = _Client(_FlakyCompletions())
        result = await agent.run("finish quickly")
        assert result["status"] == "success"
    finally:
        await sm.close()
