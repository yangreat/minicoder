"""Mock OpenAI client used by tests and demo mode."""

from typing import Any


class MockChoice:
    """Mock choice from LLM response."""

    def __init__(self, message: "MockMessage"):
        self.message = message


class MockMessage:
    """Mock message from LLM."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list["MockToolCall"] | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls


class MockFunction:
    """Mock function in tool call."""

    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class MockToolCall:
    """Mock tool call."""

    def __init__(self, id: str, function_name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = MockFunction(function_name, arguments)

    def model_dump(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "type": self.type,
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class MockUsage:
    """Mock token usage."""

    def __init__(self, total_tokens: int = 100):
        self.total_tokens = total_tokens
        self.prompt_tokens = total_tokens // 2
        self.completion_tokens = total_tokens // 2


class MockResponse:
    """Mock LLM response."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[MockToolCall] | None = None,
        usage: MockUsage | None = None,
    ):
        message = MockMessage(content=content, tool_calls=tool_calls)
        self.choices = [MockChoice(message)]
        self.usage = usage or MockUsage()


class MockLLM:
    """Mock chat.completions interface."""

    def __init__(self, responses: list[MockResponse] | None = None):
        self.responses = responses or []
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> MockResponse:
        """Return the next scripted response."""
        self.calls.append(kwargs)
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return MockResponse(content="Mock response")


class MockChat:
    """Mock chat namespace."""

    def __init__(self, responses: list[MockResponse] | None = None):
        self.completions = MockLLM(responses)


class MockOpenAI:
    """Mock AsyncOpenAI-compatible client."""

    def __init__(self, responses: list[MockResponse] | None = None):
        self.chat = MockChat(responses)
