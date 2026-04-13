"""
Tests for Persistent Conversation Memory
==========================================
Validates save, load, auto-save, and session resume.
"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path

from src.agent.memory import ConversationMemory


@pytest.fixture
def tmp_dir():
    tmpdir = tempfile.mkdtemp(prefix="persist_test_")
    yield tmpdir
    shutil.rmtree(tmpdir)


def make_memory(
    tmp_dir: str,
    max_turns: int = 20,
    auto_save: int = 5,
) -> ConversationMemory:
    """Create memory with persistence."""
    persist_path = str(
        Path(tmp_dir) / ".agent" / "conversation.json"
    )
    return ConversationMemory(
        max_turns=max_turns,
        persist_path=persist_path,
        auto_save_interval=auto_save,
    )


class TestSaveAndLoad:
    """Basic save/load functionality."""

    def test_save_creates_file(self, tmp_dir: str) -> None:
        mem = make_memory(tmp_dir)
        mem.add_user_message("Hello")
        assert mem.save()
        persist_file = Path(tmp_dir) / ".agent" / "conversation.json"
        assert persist_file.exists()

    def test_load_restores_turns(self, tmp_dir: str) -> None:
        mem1 = make_memory(tmp_dir)
        mem1.add_user_message("Question")
        mem1.add_assistant_message("Answer")
        mem1.save()

        mem2 = make_memory(tmp_dir)
        assert mem2.load()
        assert mem2.turn_count == 2
        messages = mem2.get_messages()
        assert messages[0]["content"] == "Question"
        assert messages[1]["content"] == "Answer"

    def test_load_restores_tool_results(
        self, tmp_dir: str
    ) -> None:
        mem1 = make_memory(tmp_dir)
        mem1.add_user_message("Read file")
        mem1.add_tool_result("read_file", "contents")
        mem1.save()

        mem2 = make_memory(tmp_dir)
        mem2.load()
        turns = mem2.turns
        assert turns[1].is_tool_result
        assert turns[1].tool_name == "read_file"

    def test_load_nonexistent_returns_false(
        self, tmp_dir: str
    ) -> None:
        mem = make_memory(tmp_dir)
        assert not mem.load()

    def test_save_without_persist_path(self) -> None:
        mem = ConversationMemory(max_turns=10)
        assert not mem.save()

    def test_load_without_persist_path(self) -> None:
        mem = ConversationMemory(max_turns=10)
        assert not mem.load()


class TestAutoSave:
    """Auto-save interval behavior."""

    def test_auto_saves_at_interval(
        self, tmp_dir: str
    ) -> None:
        mem = make_memory(tmp_dir, auto_save=3)
        mem.add_user_message("Turn 1")
        mem.add_assistant_message("Turn 2")
        # Not saved yet (2 turns, interval is 3)
        persist_file = Path(tmp_dir) / ".agent" / "conversation.json"
        if persist_file.exists():
            data = json.loads(persist_file.read_text())
            # Could be empty or have old data
        mem.add_user_message("Turn 3")
        # Now should auto-save (3 turns since last save)
        assert persist_file.exists()
        data = json.loads(persist_file.read_text())
        assert len(data["turns"]) == 3

    def test_auto_save_disabled_with_zero(
        self, tmp_dir: str
    ) -> None:
        mem = make_memory(tmp_dir, auto_save=0)
        for i in range(10):
            mem.add_user_message(f"Turn {i}")
        persist_file = Path(tmp_dir) / ".agent" / "conversation.json"
        # Should not have been auto-saved
        assert not persist_file.exists()


class TestClearWithPersistence:
    """Clear must remove saved file."""

    def test_clear_deletes_file(self, tmp_dir: str) -> None:
        mem = make_memory(tmp_dir)
        mem.add_user_message("Data")
        mem.save()
        persist_file = Path(tmp_dir) / ".agent" / "conversation.json"
        assert persist_file.exists()

        mem.clear()
        assert not persist_file.exists()
        assert mem.is_empty

    def test_clear_without_file_does_not_crash(
        self, tmp_dir: str
    ) -> None:
        mem = make_memory(tmp_dir)
        mem.add_user_message("Data")
        mem.clear()  # No file to delete
        assert mem.is_empty


class TestSessionResume:
    """Full session resume simulation."""

    def test_multi_session_continuity(
        self, tmp_dir: str
    ) -> None:
        # Session 1
        mem1 = make_memory(tmp_dir)
        mem1.add_user_message("What is Python?")
        mem1.add_assistant_message("A programming language.")
        mem1.save()

        # Session 2 — new instance, same path
        mem2 = make_memory(tmp_dir)
        mem2.load()
        mem2.add_user_message("Tell me more")
        mem2.add_assistant_message("It was created by Guido.")
        mem2.save()

        # Session 3 — should have all 4 turns
        mem3 = make_memory(tmp_dir)
        mem3.load()
        assert mem3.turn_count == 4
        messages = mem3.get_messages()
        assert messages[0]["content"] == "What is Python?"
        assert messages[3]["content"] == "It was created by Guido."

    def test_window_respected_across_sessions(
        self, tmp_dir: str
    ) -> None:
        mem1 = make_memory(tmp_dir, max_turns=4)
        for i in range(6):
            mem1.add_user_message(f"Q{i}")
            mem1.add_assistant_message(f"A{i}")
        mem1.save()

        mem2 = make_memory(tmp_dir, max_turns=4)
        mem2.load()
        assert mem2.turn_count == 4


class TestSummaryWithPersistence:
    """Summary shows persistence status."""

    def test_summary_shows_persistence_on(
        self, tmp_dir: str
    ) -> None:
        mem = make_memory(tmp_dir)
        mem.add_user_message("Test")
        summary = mem.get_summary()
        assert "Persistence: ON" in summary

    def test_summary_no_persistence_indicator(self) -> None:
        mem = ConversationMemory(max_turns=10)
        mem.add_user_message("Test")
        summary = mem.get_summary()
        assert "Persistence" not in summary
