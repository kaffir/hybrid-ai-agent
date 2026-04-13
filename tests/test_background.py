"""
Tests for Background Task Manager
====================================
Validates task submission, status tracking, cancellation,
and concurrency limits.
"""

import pytest
import time
from src.agent.background import (
    BackgroundTaskManager,
    TaskStatus,
)


@pytest.fixture
def manager() -> BackgroundTaskManager:
    return BackgroundTaskManager(max_concurrent=3)


def slow_task(request: str):
    """Simulate a slow task."""
    time.sleep(0.5)
    return f"Result: {request}"


def instant_task(request: str):
    """Simulate an instant task."""
    return f"Result: {request}"


def failing_task(request: str):
    """Simulate a failing task."""
    raise ValueError("Task failed")


class TestTaskSubmission:
    """Task submission and ID generation."""

    def test_submit_returns_task(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("test", instant_task)
        assert task is not None
        assert task.task_id == "bg-001"

    def test_sequential_ids(
        self, manager: BackgroundTaskManager
    ) -> None:
        t1 = manager.submit("first", instant_task)
        t2 = manager.submit("second", instant_task)
        assert t1.task_id == "bg-001"
        assert t2.task_id == "bg-002"

    def test_stores_request(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("my request", instant_task)
        assert task.request == "my request"


class TestConcurrencyLimit:
    """Maximum concurrent task enforcement."""

    def test_rejects_over_limit(
        self, manager: BackgroundTaskManager
    ) -> None:
        for i in range(3):
            manager.submit(f"task {i}", slow_task)
        # 4th should be rejected
        task = manager.submit("overflow", slow_task)
        assert task is None

    def test_accepts_after_completion(
        self, manager: BackgroundTaskManager
    ) -> None:
        for i in range(3):
            manager.submit(f"task {i}", instant_task)
        # Wait for completion
        time.sleep(0.2)
        # Should accept now
        task = manager.submit("new task", instant_task)
        assert task is not None


class TestTaskStatus:
    """Task status tracking."""

    def test_completed_status(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("test", instant_task)
        time.sleep(0.2)
        updated = manager.get_task(task.task_id)
        assert updated.status == TaskStatus.COMPLETED

    def test_failed_status(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("test", failing_task)
        time.sleep(0.2)
        updated = manager.get_task(task.task_id)
        assert updated.status == TaskStatus.FAILED
        assert updated.error is not None

    def test_result_stored(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("hello", instant_task)
        time.sleep(0.2)
        updated = manager.get_task(task.task_id)
        assert updated.result == "Result: hello"

    def test_elapsed_time_tracked(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("test", slow_task)
        time.sleep(0.7)
        updated = manager.get_task(task.task_id)
        assert updated.elapsed_seconds >= 0.4


class TestCancellation:
    """Task cancellation."""

    def test_cancel_running_task(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("test", slow_task)
        time.sleep(0.1)
        success = manager.cancel(task.task_id)
        assert success
        updated = manager.get_task(task.task_id)
        assert updated.status == TaskStatus.CANCELLED

    def test_cancel_nonexistent_task(
        self, manager: BackgroundTaskManager
    ) -> None:
        success = manager.cancel("bg-999")
        assert not success

    def test_cancel_completed_task(
        self, manager: BackgroundTaskManager
    ) -> None:
        task = manager.submit("test", instant_task)
        time.sleep(0.2)
        success = manager.cancel(task.task_id)
        assert not success


class TestTaskListing:
    """Task listing and filtering."""

    def test_list_all_tasks(
        self, manager: BackgroundTaskManager
    ) -> None:
        manager.submit("a", instant_task)
        manager.submit("b", instant_task)
        time.sleep(0.2)
        tasks = manager.list_tasks()
        assert len(tasks) == 2

    def test_list_excludes_done(
        self, manager: BackgroundTaskManager
    ) -> None:
        manager.submit("done", instant_task)
        manager.submit("running", slow_task)
        time.sleep(0.2)
        active = manager.list_tasks(include_done=False)
        # The instant task completed, slow might still be running
        assert all(not t.is_done for t in active)

    def test_clear_done(
        self, manager: BackgroundTaskManager
    ) -> None:
        manager.submit("a", instant_task)
        manager.submit("b", instant_task)
        time.sleep(0.2)
        cleared = manager.clear_done()
        assert cleared == 2
        assert len(manager.list_tasks()) == 0


class TestShortRequest:
    """Request truncation for display."""

    def test_short_request_unchanged(self) -> None:
        from src.agent.background import BackgroundTask
        task = BackgroundTask(
            task_id="bg-001",
            request="Short request",
        )
        assert task.short_request == "Short request"

    def test_long_request_truncated(self) -> None:
        from src.agent.background import BackgroundTask
        task = BackgroundTask(
            task_id="bg-001",
            request="A" * 100,
        )
        assert len(task.short_request) == 50
        assert task.short_request.endswith("...")
