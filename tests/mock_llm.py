"""Mock LLM for testing."""

from typing import Any, Dict, List, Optional


class MockChoice:
    """Mock choice from LLM response."""

    def __init__(self, message: "MockMessage"):
        self.message = message


class MockMessage:
    """Mock message from LLM."""

    def __init__(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List["MockToolCall"]] = None,
    ):
        self.content = content
        self.tool_calls = tool_calls


class MockToolCall:
    """Mock tool call."""

    def __init__(self, id: str, function_name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = MockFunction(function_name, arguments)

    def model_dump(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "type": self.type,
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class MockFunction:
    """Mock function in tool call."""

    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


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
        content: Optional[str] = None,
        tool_calls: Optional[List[MockToolCall]] = None,
        usage: Optional[MockUsage] = None,
    ):
        message = MockMessage(content=content, tool_calls=tool_calls)
        self.choices = [MockChoice(message)]
        self.usage = usage or MockUsage()


class MockLLM:
    """Mock LLM for testing."""

    def __init__(self, responses: Optional[List[MockResponse]] = None):
        self.responses = responses or []
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> MockResponse:
        """Mock create method."""
        self.calls.append(kwargs)

        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response

        return MockResponse(content="Mock response")


class MockOpenAI:
    """Mock OpenAI client."""

    def __init__(self, responses: Optional[List[MockResponse]] = None):
        self.chat = MockChat(responses)


class MockChat:
    """Mock chat completions."""

    def __init__(self, responses: Optional[List[MockResponse]] = None):
        self.completions = MockLLM(responses)
