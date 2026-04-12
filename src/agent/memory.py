"""
Conversation Memory
====================
Sliding window conversation history for multi-turn interactions.

Supports persistence to disk for session resume.

Design:
  - Fixed window size (default 20 turns)
  - Oldest turns dropped when window is exceeded
  - Tool results included in history for context continuity
  - Optional auto-save every N turns
  - JSON file storage in workspace/.agent/
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
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
    Sliding window conversation history with optional persistence.

    Maintains a bounded list of conversation turns.
    When the window is full, oldest turns are dropped.
    Can save/load to JSON for session resume.
    """

    def __init__(
        self,
        max_turns: int = 20,
        persist_path: Optional[str] = None,
        auto_save_interval: int = 5,
    ) -> None:
        """
        Args:
            max_turns: Maximum number of turns to retain.
            persist_path: Path to save/load conversation.
                          None disables persistence.
            auto_save_interval: Save every N turns (0 disables).
        """
        self._max_turns = max_turns
        self._history: list[ConversationTurn] = []
        self._persist_path = (
            Path(persist_path) if persist_path else None
        )
        self._auto_save_interval = auto_save_interval
        self._turns_since_save = 0

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

    @property
    def has_persist_path(self) -> bool:
        return self._persist_path is not None

    def add_user_message(self, content: str) -> None:
        """Add a user message to history."""
        self._history.append(
            ConversationTurn(role="user", content=content)
        )
        self._trim()
        self._maybe_auto_save()

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant response to history."""
        self._history.append(
            ConversationTurn(role="assistant", content=content)
        )
        self._trim()
        self._maybe_auto_save()

    def add_tool_result(
        self, tool_name: str, content: str
    ) -> None:
        """Add a tool result to history."""
        self._history.append(
            ConversationTurn(
                role="user",
                content=content,
                is_tool_result=True,
                tool_name=tool_name,
            )
        )
        self._trim()
        self._maybe_auto_save()

    def get_messages(self) -> list[dict]:
        """Get history as message dicts for LLM API calls."""
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
        """Get a brief summary for /history command."""
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

        status = (
            f"Conversation history ({self.turn_count}/"
            f"{self._max_turns} turns)"
        )
        if self._persist_path:
            status += " | Persistence: ON"
        return status + ":\n" + "\n".join(lines)

    def clear(self) -> None:
        """Clear all conversation history and delete saved file."""
        self._history.clear()
        self._turns_since_save = 0
        if self._persist_path and self._persist_path.exists():
            try:
                self._persist_path.unlink()
            except OSError:
                pass

    def save(self) -> bool:
        """
        Save conversation history to disk.

        Returns:
            True if saved successfully.
        """
        if not self._persist_path:
            return False

        try:
            self._persist_path.parent.mkdir(
                parents=True, exist_ok=True
            )
            data = {
                "max_turns": self._max_turns,
                "turns": [asdict(t) for t in self._history],
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._turns_since_save = 0
            return True
        except (OSError, TypeError):
            return False

    def load(self) -> bool:
        """
        Load conversation history from disk.

        Returns:
            True if loaded successfully.
        """
        if not self._persist_path:
            return False

        if not self._persist_path.exists():
            return False

        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            turns = data.get("turns", [])
            self._history = [
                ConversationTurn(
                    role=t["role"],
                    content=t["content"],
                    is_tool_result=t.get("is_tool_result", False),
                    tool_name=t.get("tool_name"),
                )
                for t in turns
            ]
            self._trim()
            return True
        except (OSError, json.JSONDecodeError, KeyError):
            return False

    def _trim(self) -> None:
        """Remove oldest turns if window is exceeded."""
        while len(self._history) > self._max_turns:
            self._history.pop(0)

    def _maybe_auto_save(self) -> None:
        """Auto-save if interval is reached."""
        if not self._persist_path:
            return
        if self._auto_save_interval <= 0:
            return
        self._turns_since_save += 1
        if self._turns_since_save >= self._auto_save_interval:
            self.save()
