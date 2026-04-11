"""
API Health Checker
==================
Monitors Claude API availability in a background thread.
Notifies the agent when the API recovers from an outage.

Security design:
  - Health check uses a minimal 1-token request (low cost)
  - No sensitive data sent in health check payloads
  - Thread-safe status access
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class HealthStatus:
    """Current health status of external services."""

    claude_api_available: bool = False
    last_check_time: float = 0.0
    last_error: Optional[str] = None
    consecutive_failures: int = 0

    @property
    def is_degraded(self) -> bool:
        """True if Claude API is unavailable."""
        return not self.claude_api_available


class HealthChecker:
    """
    Background health monitor for Claude API.

    Polls every `interval_seconds` and updates shared status.
    Calls `on_recovery` callback when API comes back online.
    """

    def __init__(
        self,
        check_fn: Callable[[], bool],
        interval_seconds: float = 60.0,
        on_recovery: Optional[Callable[[], None]] = None,
        on_failure: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Args:
            check_fn: Function that returns True if Claude API is available.
            interval_seconds: Polling interval in seconds.
            on_recovery: Callback when API recovers from outage.
            on_failure: Callback when API becomes unavailable.
        """
        self._check_fn = check_fn
        self._interval = interval_seconds
        self._on_recovery = on_recovery
        self._on_failure = on_failure
        self._status = HealthStatus()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def status(self) -> HealthStatus:
        """Thread-safe access to current health status."""
        with self._lock:
            return HealthStatus(
                claude_api_available=self._status.claude_api_available,
                last_check_time=self._status.last_check_time,
                last_error=self._status.last_error,
                consecutive_failures=self._status.consecutive_failures,
            )

    def start(self) -> None:
        """Start background health monitoring."""
        if self._thread and self._thread.is_alive():
            return  # Already running

        self._stop_event.clear()

        # Do an initial check synchronously
        self._perform_check()

        # Start background thread
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="health-checker",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop background health monitoring."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._interval)
            if self._stop_event.is_set():
                break
            self._perform_check()

    def _perform_check(self) -> None:
        """Execute a single health check."""
        was_available = self._status.claude_api_available

        try:
            is_available = self._check_fn()
        except Exception as e:
            is_available = False
            error_msg = str(e)
        else:
            error_msg = None if is_available else "Health check returned False"

        with self._lock:
            self._status.claude_api_available = is_available
            self._status.last_check_time = time.time()

            if is_available:
                self._status.last_error = None
                self._status.consecutive_failures = 0
            else:
                self._status.last_error = error_msg
                self._status.consecutive_failures += 1

        # Trigger callbacks
        if is_available and not was_available:
            # API just recovered
            if self._on_recovery:
                self._on_recovery()

        elif not is_available and was_available:
            # API just went down
            if self._on_failure:
                self._on_failure(error_msg or "Unknown error")
