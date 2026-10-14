"""End-to-end demo of MiniCoder fixing a bug with mock LLM."""

import asyncio
import json
import sys
from pathlib import Path

parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir / "src"))
sys.path.insert(0, str(parent_dir / "tests"))

from minicoder.agent import CodingAgent
from minicoder.state import StateManager
from mock_llm import MockOpenAI, MockResponse, MockToolCall


async def demo() -> None:
    """Run end-to-end demo."""
    print("=" * 60)
    print("MiniCoder End-to-End Demo")
    print("Fixing calculator divide-by-zero bug with mock LLM")
    print("=" * 60)

    calc_dir = Path(__file__).parent / "toy_repos" / "calculator"
    db_path = calc_dir / ".minicoder" / "demo.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    state_manager = StateManager(db_path)
    await state_manager.initialize()

    try:
        responses = [
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_1",
                        function_name="read_file",
                        arguments=json.dumps({"path": "README.md"}),
                    )
                ]
            ),
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_2",
                        function_name="read_file",
                        arguments=json.dumps({"path": "calculator.py"}),
                    )
                ]
            ),
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_3",
                        function_name="apply_patch",
                        arguments=json.dumps({
                            "path": "calculator.py",
                            "patch": """SEARCH:
    elif operation == "divide":
        return a / b
REPLACE:
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b"""
                        }),
                    )
                ]
            ),
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_4",
                        function_name="run_shell",
                        arguments=json.dumps({
                            "command": "python3 -m pytest test_calculator.py -v",
                            "timeout": 10
                        }),
                    )
                ]
            ),
            MockResponse(
                tool_calls=[
                    MockToolCall(
                        id="call_5",
                        function_name="finish",
                        arguments=json.dumps({
                            "message": "Fixed divide-by-zero bug. Added check before division."
                        }),
                    )
                ]
            ),
        ]

        mock_client = MockOpenAI(responses)

        agent = CodingAgent(calc_dir, state_manager, max_steps=10)
        agent.client = mock_client

        print("\n📝 Task: Fix the divide-by-zero bug in calculator.py\n")

        result = await agent.run(
            "Fix the bug in calculator.py. Read README.md for context and make all tests pass."
        )

        print("\n" + "=" * 60)
        print("Demo Results")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Run ID: {result['run_id']}")
        print(f"Steps: {result['steps']}")
        print(f"Message: {result.get('message', 'N/A')}")

        if result["status"] == "success":
            print("\n✅ Demo completed successfully!")
            print("\nCheck the fixed code:")
            fixed_code = (calc_dir / "calculator.py").read_text()
            if "Cannot divide by zero" in fixed_code:
                print("✓ Divide-by-zero check added")
            else:
                print("⚠ Fix may not have been applied correctly")
        else:
            print("\n❌ Demo failed")

        print("\n" + "=" * 60)

    finally:
        await state_manager.close()


if __name__ == "__main__":
    asyncio.run(demo())
