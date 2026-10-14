"""MiniCoder - A portfolio-quality coding agent."""

__version__ = "0.1.0"

from minicoder.agent import CodingAgent
from minicoder.state import AgentState, StateManager

__all__ = ["CodingAgent", "AgentState", "StateManager"]
