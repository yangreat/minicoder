"""Context management with token budgeting and compression."""

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False


class TokenCounter:
    """Count tokens in text."""

    def __init__(self, model: str = "gpt-4"):
        self.model = model
        if HAS_TIKTOKEN:
            try:
                self.encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                self.encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoding = None

    def count(self, text: str) -> int:
        """Count tokens in text."""
        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            return len(text) // 4


class ContextManager:
    """Manage conversation context with token budgeting."""

    def __init__(
        self,
        repo_path: Path,
        max_tokens: int = 8000,
        keep_recent: int = 5,
        model: str = "gpt-4",
    ):
        self.repo_path = repo_path
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.token_counter = TokenCounter(model)
        self.messages: list[dict[str, Any]] = []
        self.offloaded_outputs: dict[str, str] = {}
        self._output_dir = repo_path / ".minicoder" / "outputs"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def add_message(self, role: str, content: str, tool_calls: list[dict] | None = None) -> None:
        """Add a message to context."""
        message: dict[str, Any] = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        self.messages.append(message)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        """Add a tool result, offloading if too large."""
        token_count = self.token_counter.count(content)

        if token_count > 1000:
            file_path = self._offload_output(tool_call_id, content)
            content = f"[Output saved to {file_path} ({token_count} tokens)]"

        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    def _offload_output(self, tool_call_id: str, content: str) -> Path:
        """Offload large output to a file."""
        file_hash = hashlib.md5(tool_call_id.encode()).hexdigest()[:8]
        file_path = self._output_dir / f"output_{file_hash}.txt"
        file_path.write_text(content, encoding="utf-8")
        self.offloaded_outputs[tool_call_id] = str(file_path)
        return file_path.relative_to(self.repo_path)

    def get_messages(self, include_system: bool = True) -> list[dict[str, Any]]:
        """Get messages within token budget."""
        if not self.messages:
            return []

        total_tokens = sum(self.token_counter.count(self._message_text(m)) for m in self.messages)

        if total_tokens <= self.max_tokens:
            return self.messages.copy()

        recent_messages = self.messages[-self.keep_recent :]
        older_messages = self.messages[: -self.keep_recent]

        if older_messages:
            summary = self._summarize_messages(older_messages)
            summary_message = {
                "role": "system",
                "content": f"[Previous conversation summary]\n{summary}",
            }
            return [summary_message] + recent_messages
        else:
            return recent_messages

    def _message_text(self, message: dict[str, Any]) -> str:
        """Extract text from a message for token counting."""
        parts = [message.get("content", "")]
        if "tool_calls" in message:
            parts.extend(json.dumps(tc) for tc in message["tool_calls"])
        return " ".join(filter(None, parts))

    def _summarize_messages(self, messages: list[dict[str, Any]]) -> str:
        """Create a summary of messages."""
        summary_parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "assistant" and "tool_calls" in msg:
                tools = [tc["function"]["name"] for tc in msg["tool_calls"]]
                summary_parts.append(f"Agent called: {', '.join(tools)}")
            elif role == "tool":
                summary_parts.append(f"Tool result: {content[:100]}")
            elif content:
                summary_parts.append(f"{role}: {content[:200]}")

        return "\n".join(summary_parts[:20])

    def load_project_memory(self) -> str | None:
        """Load project memory file if it exists."""
        memory_files = ["AGENTS.md", ".agents.md", "MEMORY.md"]

        for filename in memory_files:
            path = self.repo_path / filename
            if path.exists():
                return path.read_text(encoding="utf-8")

        return None

    def get_system_prompt(self) -> str:
        """Build system prompt with project context."""
        parts = [
            "You are MiniCoder, an expert coding agent. Your task is to help fix bugs and implement features.",
            "You have access to various tools to read, write, and modify code files.",
            "Always think step by step and explain your reasoning.",
            "When you're done with the task, call the 'finish' function.",
        ]

        project_memory = self.load_project_memory()
        if project_memory:
            parts.append(f"\n## Project Context\n{project_memory}")

        return "\n\n".join(parts)

    def estimate_usage(self) -> dict[str, int]:
        """Estimate current token usage."""
        total = sum(self.token_counter.count(self._message_text(m)) for m in self.messages)
        system = self.token_counter.count(self.get_system_prompt())

        return {
            "messages": total,
            "system": system,
            "total": total + system,
            "budget": self.max_tokens,
            "remaining": max(0, self.max_tokens - total - system),
        }
