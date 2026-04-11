"""
Pending Task Queue
==================
Persists blocked tasks to disk for later retry when
Claude API recovers.

Storage: /workspace/.agent/pending_tasks.json

Security design:
  - File stored inside sandbox workspace only
  - No sensitive data beyond the original request text
  - JSON format for auditability
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class PendingTask:
    """A task that was blocked due to API unavailability."""

    task_id: str
    timestamp: float
    original_request: str
    classification: str  # e.g., "security", "complex"
    blocked_reason: str
    status: str = "pending"  # pending, completed, discarded
    context: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        original_request: str,
        classification: str,
        blocked_reason: str,
        context: Optional[dict] = None,
    ) -> PendingTask:
        """Create a new pending task with generated ID and timestamp."""
        return cls(
            task_id=uuid.uuid4().hex[:8],
            timestamp=time.time(),
            original_request=original_request,
            classification=classification,
            blocked_reason=blocked_reason,
            context=context or {},
        )


class PendingTaskQueue:
    """
    Persistent queue for blocked tasks.

    Tasks are stored as JSON on disk inside the workspace.
    """

    def __init__(
        self, workspace_root: str = "/workspace"
    ) -> None:
        self._queue_dir = Path(workspace_root) / ".agent"
        self._queue_file = self._queue_dir / "pending_tasks.json"
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create storage directory if it doesn't exist."""
        self._queue_dir.mkdir(parents=True, exist_ok=True)
        if not self._queue_file.exists():
            self._save_tasks([])

    def _load_tasks(self) -> list[dict]:
        """Load tasks from disk."""
        try:
            with open(self._queue_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_tasks(self, tasks: list[dict]) -> None:
        """Save tasks to disk."""
        with open(self._queue_file, "w") as f:
            json.dump(tasks, f, indent=2)

    def add(self, task: PendingTask) -> str:
        """
        Add a task to the pending queue.

        Returns:
            The task ID.
        """
        tasks = self._load_tasks()
        tasks.append(asdict(task))
        self._save_tasks(tasks)
        return task.task_id

    def list_pending(self) -> list[PendingTask]:
        """Get all pending tasks."""
        tasks = self._load_tasks()
        return [
            PendingTask(**t) for t in tasks
            if t.get("status") == "pending"
        ]

    def get(self, task_id: str) -> Optional[PendingTask]:
        """Get a specific task by ID."""
        tasks = self._load_tasks()
        for t in tasks:
            if t.get("task_id") == task_id:
                return PendingTask(**t)
        return None

    def mark_completed(self, task_id: str) -> bool:
        """Mark a task as completed."""
        return self._update_status(task_id, "completed")

    def mark_discarded(self, task_id: str) -> bool:
        """Mark a task as discarded."""
        return self._update_status(task_id, "discarded")

    def _update_status(self, task_id: str, status: str) -> bool:
        """Update a task's status."""
        tasks = self._load_tasks()
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                self._save_tasks(tasks)
                return True
        return False

    def clear_all(self) -> int:
        """
        Discard all pending tasks.

        Returns:
            Number of tasks cleared.
        """
        tasks = self._load_tasks()
        count = 0
        for t in tasks:
            if t.get("status") == "pending":
                t["status"] = "discarded"
                count += 1
        self._save_tasks(tasks)
        return count

    @property
    def pending_count(self) -> int:
        """Number of pending tasks."""
        return len(self.list_pending())
