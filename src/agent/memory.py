"""
Conversation Memory
====================
Sliding window conversation history for multi-turn interactions.

Maintains a bounded history of user messages, assistant responses,
and tool interactions within a single session.

Design:
  - Fixed window size (default 20 turns)
  - Oldest turns dropped when window is exceeded
  - Tool results included in history for context continuity
  - Session-scoped — resets on agent restart
  - System prompt is NOT part of the window (always included)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ConversationTurn:
    """A single turn in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    is_tool_result: bool = False
    tool_name: Optional[str] = None


class ConversationMemory:
    """
    Sliding window conversation history.

    Maintains a bounded list of conversation turns.
    When the window is full, oldest turns are dropped.
    """

    def __init__(self, max_turns: int = 20) -> None:
        """
        Args:
            max_turns: Maximum number of turns to retain.
                       Each user message + assistant response = 2 turns.
        """
        self._max_turns = max_turns
        self._history: list[ConversationTurn] = []

    @property
    def turns(self) -> list[ConversationTurn]:
        """Current conversation history."""
        return list(self._history)

    @property
    def turn_count(self) -> int:
        """Number of turns in history."""
        return len(self._history)

    @property
    def is_empty(self) -> bool:
        return len(self._history) == 0

    def add_user_message(self, content: str) -> None:
        """Add a user message to history."""
        self._history.append(
            ConversationTurn(role="user", content=content)
        )
        self._trim()

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant response to history."""
        self._history.append(
            ConversationTurn(role="assistant", content=content)
        )
        self._trim()

    def add_tool_result(
        self, tool_name: str, content: str
    ) -> None:
        """
        Add a tool result to history.

        Tool results are stored as user messages (the convention
        for feeding results back to the LLM).
        """
        self._history.append(
            ConversationTurn(
                role="user",
                content=content,
                is_tool_result=True,
                tool_name=tool_name,
            )
        )
        self._trim()

    def get_messages(self) -> list[dict]:
        """
        Get conversation history as a list of message dicts
        suitable for LLM API calls.

        Returns:
            List of {"role": str, "content": str} dicts.
        """
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self._history
        ]

    def get_last_user_message(self) -> Optional[str]:
        """Get the most recent user message."""
        for turn in reversed(self._history):
            if turn.role == "user" and not turn.is_tool_result:
                return turn.content
        return None

    def get_summary(self) -> str:
        """
        Get a brief summary of the conversation history.

        Useful for debugging and /history command.
        """
        if self.is_empty:
            return "No conversation history."

        lines = []
        for i, turn in enumerate(self._history):
            role = turn.role.upper()
            if turn.is_tool_result:
                role = f"TOOL({turn.tool_name})"
            preview = turn.content[:60].replace("\n", " ")
            if len(turn.content) > 60:
                preview += "..."
            lines.append(f"  {i + 1}. [{role}] {preview}")

        return (
            f"Conversation history ({self.turn_count}/"
            f"{self._max_turns} turns):\n"
            + "\n".join(lines)
        )

    def clear(self) -> None:
        """Clear all conversation history."""
        self._history.clear()

    def _trim(self) -> None:
        """Remove oldest turns if window is exceeded."""
        while len(self._history) > self._max_turns:
            self._history.pop(0)
