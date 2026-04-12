"""
Background Task Manager
========================
Runs agent requests in background threads so the user
can continue working on other tasks.

Design:
  - Maximum 3 concurrent tasks
  - Tasks inherit current agent mode
  - File write approvals pause the background task
  - Thread-safe status tracking
  - Cancellation via interrupt flag

Security design:
  - Background tasks go through the same security pipeline
  - No elevated privileges for background execution
  - All tool calls still require approval (unless auto-approve is on)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class TaskStatus(str, Enum):
    """Background task status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class BackgroundTask:
    """A background task with its state and result."""

    task_id: str
    request: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    thread: Optional[threading.Thread] = None
    cancel_flag: threading.Event = field(
        default_factory=threading.Event
    )

    @property
    def elapsed_seconds(self) -> float:
        """Time elapsed since task started."""
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    @property
    def short_request(self) -> str:
        """Truncated request for display."""
        if len(self.request) <= 50:
            return self.request
        return self.request[:47] + "..."

    @property
    def is_done(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )


class BackgroundTaskManager:
    """
    Manages background execution of agent requests.

    Thread-safe task tracking with configurable concurrency limit.
    """

    def __init__(self, max_concurrent: int = 3) -> None:
        self._max_concurrent = max_concurrent
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()
        self._task_counter = 0

    def _generate_id(self) -> str:
        """Generate a sequential task ID."""
        self._task_counter += 1
        return f"bg-{self._task_counter:03d}"

    @property
    def active_count(self) -> int:
        """Number of currently running tasks."""
        with self._lock:
            return sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.RUNNING
            )

    def submit(
        self,
        request: str,
        execute_fn: Callable[[str], Any],
    ) -> Optional[BackgroundTask]:
        """
        Submit a request for background execution.

        Args:
            request: The user's request string.
            execute_fn: Function to call with the request.
                        Should return an AgentState.

        Returns:
            BackgroundTask if submitted, None if at capacity.
        """
        if self.active_count >= self._max_concurrent:
            return None

        task_id = self._generate_id()
        task = BackgroundTask(
            task_id=task_id,
            request=request,
        )

        thread = threading.Thread(
            target=self._run_task,
            args=(task, execute_fn),
            daemon=True,
            name=f"bg-task-{task_id}",
        )
        task.thread = thread

        with self._lock:
            self._tasks[task_id] = task

        thread.start()

        return task

    def _run_task(
        self,
        task: BackgroundTask,
        execute_fn: Callable[[str], Any],
    ) -> None:
        """Execute a task in background thread."""
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()

        try:
            # Check cancel before starting
            if task.cancel_flag.is_set():
                task.status = TaskStatus.CANCELLED
                task.end_time = time.time()
                return

            result = execute_fn(task.request)
            task.end_time = time.time()

            if task.cancel_flag.is_set():
                task.status = TaskStatus.CANCELLED
            elif hasattr(result, "error") and result.error:
                task.status = TaskStatus.FAILED
                task.error = result.error
                task.result = result
            else:
                task.status = TaskStatus.COMPLETED
                task.result = result

        except KeyboardInterrupt:
            task.status = TaskStatus.CANCELLED
            task.end_time = time.time()
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.end_time = time.time()

    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """
        Cancel a running task.

        Sets the cancel flag — the task will stop at the next
        checkpoint (between ReAct iterations).

        Returns:
            True if task found and cancel requested.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.is_done:
                return False
            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            task.end_time = time.time()
            return True

    def list_tasks(
        self, include_done: bool = True
    ) -> list[BackgroundTask]:
        """
        List all tasks.

        Args:
            include_done: Include completed/failed/cancelled tasks.

        Returns:
            List of tasks, newest first.
        """
        with self._lock:
            tasks = list(self._tasks.values())

        if not include_done:
            tasks = [t for t in tasks if not t.is_done]

        return list(reversed(tasks))

    def clear_done(self) -> int:
        """
        Remove completed/failed/cancelled tasks from the list.

        Returns:
            Number of tasks cleared.
        """
        with self._lock:
            done_ids = [
                tid for tid, t in self._tasks.items()
                if t.is_done
            ]
            for tid in done_ids:
                del self._tasks[tid]
            return len(done_ids)
