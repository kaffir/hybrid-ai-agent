"""
LangGraph Agent — ReAct Loop
=============================
Implements the Reason-Act-Observe loop with routing,
model resolution, timeout control, and interrupt handling.

Security design:
  - All tool executions go through permission layer (Step 7)
  - Model selection is mode-aware (HYBRID / LOCAL_ONLY)
  - Security tasks produce disclaimers in LOCAL_ONLY mode
  - Failed cloud calls trigger fallback with pending queue
  - Per-tier timeouts prevent hung requests
  - Ctrl+C interrupts cancel current request gracefully
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import yaml

from src.router.rule_router import RuleRouter, RoutingResult, Tier
from src.models.model_resolver import ModelResolver, ModelAssignment, AgentMode
from src.models.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelError,
    OllamaTimeoutError,
)
from src.models.claude_client import (
    ClaudeClient,
    ClaudeConnectionError,
    ClaudeAuthError,
    ClaudeRateLimitError,
    ClaudeTimeoutError,
    ClaudeAPIError,
)
from src.models.health_checker import HealthChecker
from src.models.pending_queue import PendingTaskQueue, PendingTask


@dataclass
class AgentState:
    """Tracks the current state of an agent execution."""

    user_request: str = ""
    routing_result: Optional[RoutingResult] = None
    model_assignment: Optional[ModelAssignment] = None
    response: str = ""
    error: Optional[str] = None
    requires_disclaimer: bool = False
    disclaimer_shown: bool = False
    pending_task_id: Optional[str] = None
    cancelled: bool = False
    timed_out: bool = False
    iteration: int = 0
    max_iterations: int = 10


class Agent:
    """
    Hybrid AI Coding Agent.

    Orchestrates routing, model selection, and response generation
    with fallback handling, timeouts, and pending task management.
    """

    def __init__(
        self,
        ollama_client: OllamaClient,
        claude_client: ClaudeClient,
        router: RuleRouter,
        resolver: ModelResolver,
        health_checker: HealthChecker,
        pending_queue: PendingTaskQueue,
        system_prompt: Optional[str] = None,
        config_path: str = "config/routing_rules.yml",
    ) -> None:
        self._ollama = ollama_client
        self._claude = claude_client
        self._router = router
        self._resolver = resolver
        self._health = health_checker
        self._queue = pending_queue
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._tier_timeouts = self._load_tier_timeouts(config_path)

    def _load_tier_timeouts(self, config_path: str) -> dict[Tier, float]:
        """Load per-tier timeout configuration."""
        defaults = {
            Tier.SIMPLE: 30.0,
            Tier.MEDIUM: 120.0,
            Tier.COMPLEX: 180.0,
        }
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            timeouts = config.get("tier_timeouts", {})
            for tier_name, seconds in timeouts.items():
                tier = Tier(tier_name)
                defaults[tier] = float(seconds)
        except (FileNotFoundError, ValueError, yaml.YAMLError):
            pass  # Use defaults
        return defaults

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are a highly capable AI coding assistant. "
            "You help with code generation, debugging, refactoring, "
            "architecture review, and security analysis. "
            "Be concise, accurate, and security-conscious. "
            "Always explain your reasoning."
        )

    def get_timeout_for_tier(self, tier: Tier) -> float:
        """Get the configured timeout for a tier."""
        return self._tier_timeouts.get(tier, 120.0)

    def process_request(self, user_request: str) -> AgentState:
        """
        Process a user request through the full agent pipeline.

        Supports Ctrl+C interruption via KeyboardInterrupt.

        Args:
            user_request: The user's raw input.

        Returns:
            AgentState with the final response or error.
        """
        state = AgentState(user_request=user_request)

        try:
            # ── Step 1: Route ──
            state.routing_result = self._router.classify(user_request)

            # ── Step 2: Resolve model ──
            is_security = (
                state.routing_result.security_override
                if state.routing_result
                else False
            )
            state.model_assignment = self._resolver.resolve(
                tier=state.routing_result.tier,
                is_security_task=is_security,
            )
            state.requires_disclaimer = (
                state.model_assignment.requires_disclaimer
            )

            # ── Step 3: Get timeout for this tier ──
            timeout = self.get_timeout_for_tier(state.routing_result.tier)

            # ── Step 4: Generate response ──
            if state.model_assignment.provider == "ollama":
                state = self._call_ollama(state, timeout)
            else:
                state = self._call_claude(state, timeout)

        except KeyboardInterrupt:
            state.cancelled = True
            state.error = "⚠️  Request cancelled by user (Ctrl+C)."

        return state

    def _call_ollama(
        self, state: AgentState, timeout: float
    ) -> AgentState:
        """Generate response from local Ollama model."""
        messages = [{"role": "user", "content": state.user_request}]

        try:
            response = self._ollama.chat(
                model=state.model_assignment.model,
                messages=messages,
                system_prompt=self._system_prompt,
                timeout_seconds=timeout,
            )
            state.response = response.content
        except OllamaTimeoutError:
            state.timed_out = True
            tier = state.routing_result.tier.value if state.routing_result else "?"
            state.error = (
                f"⏱️  Request timed out ({timeout:.0f}s limit for {tier} tier).\n"
                f"   Suggestion: Break the task into smaller pieces, "
                f"or increase the timeout in config/routing_rules.yml."
            )
        except OllamaConnectionError as e:
            state.error = f"Ollama connection failed: {e}"
        except OllamaModelError as e:
            state.error = f"Ollama model error: {e}"

        return state

    def _call_claude(
        self, state: AgentState, timeout: float
    ) -> AgentState:
        """Generate response from Claude API with fallback handling."""
        messages = [{"role": "user", "content": state.user_request}]

        try:
            response = self._claude.chat(
                messages=messages,
                system_prompt=self._system_prompt,
                timeout_seconds=timeout,
            )
            state.response = response.content
            return state

        except ClaudeTimeoutError:
            state.timed_out = True
            state.error = (
                f"⏱️  Claude API timed out ({timeout:.0f}s limit).\n"
                f"   Suggestion: Break the task into smaller pieces, "
                f"or increase the timeout in config/routing_rules.yml."
            )
            return state

        except (ClaudeConnectionError, ClaudeRateLimitError) as e:
            return self._handle_cloud_failure(state, str(e))

        except ClaudeAuthError as e:
            state.error = (
                f"Claude API authentication failed: {e}. "
                f"Check your ANTHROPIC_API_KEY or switch to LOCAL_ONLY mode."
            )
            return state

        except ClaudeAPIError as e:
            state.error = f"Claude API error: {e}"
            return state

    def _handle_cloud_failure(
        self, state: AgentState, error_msg: str
    ) -> AgentState:
        """
        Handle Claude API failure with Option B strategy:
        - Non-security: fallback to local with warning
        - Security: block and offer pending queue
        """
        is_security = (
            state.routing_result.security_override
            if state.routing_result
            else False
        )

        if is_security:
            pending = PendingTask.create(
                original_request=state.user_request,
                classification="security",
                blocked_reason=error_msg,
            )
            task_id = self._queue.add(pending)
            state.pending_task_id = task_id
            state.error = (
                f"⛔ SECURITY TASK BLOCKED\n"
                f"Claude API is unavailable: {error_msg}\n\n"
                f"Security tasks cannot be processed by local models "
                f"(zero-tolerance policy).\n\n"
                f"Task saved to pending queue: {task_id}\n"
                f"Use '/retry {task_id}' when API recovers, "
                f"or '/pending' to view all pending tasks."
            )
        else:
            fallback_timeout = self.get_timeout_for_tier(Tier.MEDIUM)
            state.model_assignment = self._resolver.resolve(
                tier=Tier.MEDIUM, is_security_task=False
            )
            state = self._call_ollama(state, fallback_timeout)
            if not state.error:
                state.response = (
                    f"⚠️  DEGRADED MODE — Claude API unavailable, "
                    f"using local model ({state.model_assignment.model})\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{state.response}"
                )

        return state

    def retry_pending(self, task_id: str) -> Optional[AgentState]:
        """Retry a pending task."""
        task = self._queue.get(task_id)
        if not task or task.status != "pending":
            return None

        state = self.process_request(task.original_request)

        if not state.error:
            self._queue.mark_completed(task_id)

        return state

    def retry_all_pending(self) -> list[tuple[str, AgentState]]:
        """Retry all pending tasks."""
        results = []
        for task in self._queue.list_pending():
            state = self.retry_pending(task.task_id)
            if state:
                results.append((task.task_id, state))
        return results

    @property
    def mode(self) -> AgentMode:
        """Current agent operation mode."""
        return self._resolver.mode

    def set_mode(self, mode: AgentMode) -> None:
        """Switch operation mode."""
        self._resolver.set_mode(mode)

    @property
    def pending_count(self) -> int:
        """Number of pending tasks."""
        return self._queue.pending_count
