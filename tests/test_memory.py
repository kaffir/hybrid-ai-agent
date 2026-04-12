"""
Tests for Conversation Memory
================================
Validates sliding window, turn management, and history retrieval.
"""

import pytest
from src.agent.memory import ConversationMemory


@pytest.fixture
def memory() -> ConversationMemory:
    return ConversationMemory(max_turns=10)


class TestBasicOperations:
    """Core memory operations."""

    def test_starts_empty(self, memory: ConversationMemory) -> None:
        assert memory.is_empty
        assert memory.turn_count == 0

    def test_add_user_message(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("Hello")
        assert memory.turn_count == 1
        assert not memory.is_empty

    def test_add_assistant_message(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("Hello")
        memory.add_assistant_message("Hi there!")
        assert memory.turn_count == 2

    def test_add_tool_result(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_tool_result(
            "read_file", "file contents here"
        )
        assert memory.turn_count == 1
        turns = memory.turns
        assert turns[0].is_tool_result
        assert turns[0].tool_name == "read_file"

    def test_get_messages_format(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("Read file.py")
        memory.add_assistant_message("Here are the contents.")
        messages = memory.get_messages()
        assert len(messages) == 2
        assert messages[0] == {
            "role": "user",
            "content": "Read file.py",
        }
        assert messages[1] == {
            "role": "assistant",
            "content": "Here are the contents.",
        }

    def test_get_last_user_message(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("First question")
        memory.add_assistant_message("First answer")
        memory.add_user_message("Second question")
        assert memory.get_last_user_message() == "Second question"

    def test_get_last_user_message_skips_tool_results(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("Read the file")
        memory.add_assistant_message("Calling read_file...")
        memory.add_tool_result("read_file", "contents")
        assert memory.get_last_user_message() == "Read the file"

    def test_clear(self, memory: ConversationMemory) -> None:
        memory.add_user_message("Hello")
        memory.add_assistant_message("Hi")
        memory.clear()
        assert memory.is_empty
        assert memory.turn_count == 0


class TestSlidingWindow:
    """Window must trim oldest turns when full."""

    def test_window_trims_oldest(self) -> None:
        memory = ConversationMemory(max_turns=4)
        memory.add_user_message("Turn 1")
        memory.add_assistant_message("Response 1")
        memory.add_user_message("Turn 2")
        memory.add_assistant_message("Response 2")
        # Window full (4 turns)
        assert memory.turn_count == 4

        # Add one more — oldest should be dropped
        memory.add_user_message("Turn 3")
        assert memory.turn_count == 4
        messages = memory.get_messages()
        # "Turn 1" should be gone
        assert messages[0]["content"] == "Response 1"

    def test_window_preserves_order(self) -> None:
        memory = ConversationMemory(max_turns=6)
        for i in range(5):
            memory.add_user_message(f"Q{i}")
            memory.add_assistant_message(f"A{i}")

        # 10 turns added, window is 6, so oldest 4 dropped
        # Remaining: Q2, A2, Q3, A3, Q4, A4
        messages = memory.get_messages()
        assert len(messages) == 6
        assert messages[0]["content"] == "Q2"
        assert messages[-1]["content"] == "A4"

    def test_large_conversation_stays_bounded(self) -> None:
        memory = ConversationMemory(max_turns=10)
        for i in range(100):
            memory.add_user_message(f"Message {i}")
            memory.add_assistant_message(f"Reply {i}")
        assert memory.turn_count == 10


class TestSummary:
    """Summary output for /history command."""

    def test_empty_summary(
        self, memory: ConversationMemory
    ) -> None:
        summary = memory.get_summary()
        assert "No conversation history" in summary

    def test_summary_shows_turns(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("Hello")
        memory.add_assistant_message("Hi!")
        summary = memory.get_summary()
        assert "2/10 turns" in summary
        assert "USER" in summary
        assert "ASSISTANT" in summary

    def test_summary_shows_tool_results(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("Read test.py")
        memory.add_tool_result("read_file", "file contents")
        summary = memory.get_summary()
        assert "TOOL(read_file)" in summary

    def test_summary_truncates_long_content(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_user_message("x" * 200)
        summary = memory.get_summary()
        assert "..." in summary
