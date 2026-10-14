"""Test agent with mock LLM."""

import json
from pathlib import Path

import pytest

from minicoder.agent import CodingAgent
from minicoder.state import StateManager
from tests.mock_llm import MockOpenAI, MockResponse, MockToolCall


@pytest.mark.asyncio
async def test_agent_simple_task(tmp_path: Path) -> None:
    """Test agent with a simple task using mock LLM."""
    db_path = tmp_path / "test.db"
    state_manager = StateManager(db_path)
    await state_manager.initialize()

    try:
        responses = [
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_1",
                        function_name="write_file",
                        arguments=json.dumps({"path": "hello.txt", "content": "Hello, World!"}),
                    )
                ]
            ),
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_2",
                        function_name="finish",
                        arguments=json.dumps({"message": "Created hello.txt"}),
                    )
                ]
            ),
        ]

        mock_client = MockOpenAI(responses)

        agent = CodingAgent(tmp_path, state_manager, max_steps=10)
        agent.client = mock_client

        result = await agent.run("Create a hello.txt file")

        print(f"Result: {result}")
        if result["status"] != "success":
            print(f"Error message: {result.get('message', 'No message')}")

        status = result["status"]
        assert status == "success", f"Expected success but got {status}: {result.get('message', '')}"
        assert (tmp_path / "hello.txt").exists()
        assert (tmp_path / "hello.txt").read_text() == "Hello, World!"

    finally:
        await state_manager.close()


@pytest.mark.asyncio
async def test_agent_resume(tmp_path: Path) -> None:
    """Test resuming an agent run."""
    db_path = tmp_path / "test.db"
    state_manager = StateManager(db_path)
    await state_manager.initialize()

    try:
        responses_1 = [
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_1",
                        function_name="write_file",
                        arguments=json.dumps({"path": "file1.txt", "content": "Content 1"}),
                    )
                ]
            ),
        ]

        mock_client_1 = MockOpenAI(responses_1)
        agent_1 = CodingAgent(tmp_path, state_manager, max_steps=2)
        agent_1.client = mock_client_1

        result_1 = await agent_1.run("Create files")
        run_id = result_1["run_id"]

        responses_2 = [
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_2",
                        function_name="finish",
                        arguments=json.dumps({"message": "All done"}),
                    )
                ]
            )
        ]

        mock_client_2 = MockOpenAI(responses_2)
        agent_2 = CodingAgent(tmp_path, state_manager, max_steps=10)
        agent_2.client = mock_client_2

        result_2 = await agent_2.resume(run_id)

        assert result_2["status"] == "success"
        assert (tmp_path / "file1.txt").exists()

    finally:
        await state_manager.close()
