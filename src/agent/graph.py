"""
LangGraph Agent — ReAct Loop
=============================
Multi-step Reason-Act-Observe loop.

Flow:
  1. User request + system prompt → LLM
  2. LLM responds with reasoning + tool call OR final answer
  3. If tool call → execute through security pipeline → feed result back → goto 2
  4. If final answer → return to user
  5. If max iterations reached → force final answer

Security design:
  - All tool executions go through ToolExecutor (security pipeline)
  - Iteration limit prevents infinite loops
  - Security tasks produce disclaimers in LOCAL_ONLY mode
  - Failed cloud calls trigger fallback with pending queue
  - Output sanitization on final response
  - Per-tier timeouts on each LLM call
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml
from rich.console import Console

from src.router.rule_router import RuleRouter, RoutingResult, Tier
from src.models.model_resolver import (
    ModelResolver,
    ModelAssignment,
    AgentMode,
)
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
from src.agent.tool_interface import (
    build_system_prompt,
    parse_llm_output,
)
from src.agent.tool_executor import ToolExecutor
from src.security.sanitizer import Sanitizer


console = Console()


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
    tool_calls_made: list[str] = field(default_factory=list)


class Agent:
    """
    Hybrid AI Coding Agent with ReAct loop.

    Orchestrates routing, model selection, multi-step tool
    execution, and response generation with fallback handling.
    """

    def __init__(
        self,
        ollama_client: OllamaClient,
        claude_client: ClaudeClient,
        router: RuleRouter,
        resolver: ModelResolver,
        health_checker: HealthChecker,
        pending_queue: PendingTaskQueue,
        tool_executor: ToolExecutor,
        sanitizer: Sanitizer,
        system_prompt: Optional[str] = None,
        config_path: str = "config/routing_rules.yml",
        default_max_iterations: int = 10,
    ) -> None:
        self._ollama = ollama_client
        self._claude = claude_client
        self._router = router
        self._resolver = resolver
        self._health = health_checker
        self._queue = pending_queue
        self._executor = tool_executor
        self._sanitizer = sanitizer
        self._system_prompt = build_system_prompt(
            system_prompt or ""
        )
        self._tier_timeouts = self._load_tier_timeouts(config_path)
        self._default_max_iterations = default_max_iterations

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
            pass
        return defaults

    def get_timeout_for_tier(self, tier: Tier) -> float:
        """Get the configured timeout for a tier."""
        return self._tier_timeouts.get(tier, 120.0)

    def process_request(
        self,
        user_request: str,
        max_iterations: Optional[int] = None,
    ) -> AgentState:
        """
        Process a user request through the ReAct loop.

        Args:
            user_request: The user's raw input.
            max_iterations: Override default iteration limit.

        Returns:
            AgentState with the final response or error.
        """
        state = AgentState(
            user_request=user_request,
            max_iterations=max_iterations or self._default_max_iterations,
        )

        try:
            # ── Step 1: Input sanitization ──
            sanitized = self._sanitizer.check_input(user_request)
            if not sanitized.is_clean:
                console.print(
                    "[yellow]⚠️  Suspicious input detected:[/yellow]"
                )
                for warning in sanitized.warnings:
                    console.print(f"   [yellow]• {warning}[/yellow]")
                console.print()

            # ── Step 2: Route ──
            state.routing_result = self._router.classify(user_request)

            # ── Step 3: Resolve model ──
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

            # ── Step 4: Run ReAct loop ──
            timeout = self.get_timeout_for_tier(
                state.routing_result.tier
            )
            state = self._react_loop(state, timeout)

            # ── Step 5: Sanitize output ──
            if state.response:
                output_check = self._sanitizer.check_output(
                    state.response
                )
                if not output_check.is_clean:
                    console.print(
                        "[yellow]⚠️  Sensitive data redacted "
                        "from response:[/yellow]"
                    )
                    for warning in output_check.warnings:
                        console.print(
                            f"   [yellow]• {warning}[/yellow]"
                        )
                    state.response = output_check.sanitized

        except KeyboardInterrupt:
            state.cancelled = True
            state.error = "⚠️  Request cancelled by user (Ctrl+C)."

        return state

    def _react_loop(
        self, state: AgentState, timeout: float
    ) -> AgentState:
        """
        Execute the Reason-Act-Observe loop.

        Each iteration:
          1. Send conversation to LLM
          2. Parse response for tool calls or final answer
          3. If tool call → execute → add result to conversation
          4. If final answer → return
          5. If max iterations → force stop
        """
        # Build conversation history
        messages: list[dict] = [
            {"role": "user", "content": state.user_request},
        ]

        for iteration in range(state.max_iterations):
            state.iteration = iteration + 1

            # Show iteration indicator
            console.print(
                f"[dim]  [Step {state.iteration}/"
                f"{state.max_iterations}][/dim]",
                end="",
            )

            # ── Call LLM ──
            llm_response = self._call_llm(
                state, messages, timeout
            )
            if llm_response is None:
                # Error already set in state
                return state

            # ── Parse response ──
            parsed = parse_llm_output(llm_response)

            # Show reasoning
            if parsed.reasoning:
                console.print(
                    f" [dim]{parsed.reasoning[:80]}...[/dim]"
                    if len(parsed.reasoning) > 80
                    else f" [dim]{parsed.reasoning}[/dim]"
                )
            else:
                console.print()

            # ── Check for final answer ──
            if parsed.is_final:
                state.response = parsed.final_answer or ""
                return state

            # ── Check for tool calls ──
            if parsed.has_tool_calls:
                tool_call = parsed.tool_calls[0]  # One per iteration

                console.print(
                    f"[dim]  [Tool: {tool_call.tool}"
                    f"({tool_call.params})][/dim]"
                )

                # Execute through security pipeline
                tool_result = self._executor.execute(tool_call)
                state.tool_calls_made.append(tool_call.tool)

                # Add assistant response + tool result to history
                messages.append({
                    "role": "assistant",
                    "content": llm_response,
                })
                messages.append({
                    "role": "user",
                    "content": tool_result.format_for_llm(),
                })

                continue

            # ── No tool call and no final answer ──
            if parsed.has_errors:
                # LLM produced malformed output — ask to retry
                error_feedback = (
                    "Your previous response contained a malformed "
                    "tool call. Please fix the JSON format and try "
                    "again. Use the exact format:\n"
                    "<tool_call>\n"
                    '{"tool": "tool_name", "params": {...}}\n'
                    "</tool_call>"
                )
                messages.append({
                    "role": "assistant",
                    "content": llm_response,
                })
                messages.append({
                    "role": "user",
                    "content": error_feedback,
                })
                continue

            # LLM responded with plain text (no tags)
            # Treat as final answer
            state.response = parsed.reasoning or llm_response
            return state

        # Max iterations reached
        state.response = (
            f"⚠️  Reached maximum iterations "
            f"({state.max_iterations}). "
            f"Last reasoning:\n\n"
            f"{parsed.reasoning if 'parsed' in dir() else llm_response}"
        )
        return state

    def _call_llm(
        self,
        state: AgentState,
        messages: list[dict],
        timeout: float,
    ) -> Optional[str]:
        """
        Call the appropriate LLM based on model assignment.

        Returns:
            LLM response text, or None if error (error set in state).
        """
        if state.model_assignment.provider == "ollama":
            return self._call_ollama(state, messages, timeout)
        else:
            return self._call_claude(state, messages, timeout)

    def _call_ollama(
        self,
        state: AgentState,
        messages: list[dict],
        timeout: float,
    ) -> Optional[str]:
        """Call local Ollama model."""
        try:
            response = self._ollama.chat(
                model=state.model_assignment.model,
                messages=messages,
                system_prompt=self._system_prompt,
                timeout_seconds=timeout,
            )
            return response.content
        except OllamaTimeoutError:
            tier = (
                state.routing_result.tier.value
                if state.routing_result
                else "?"
            )
            state.timed_out = True
            state.error = (
                f"⏱️  Request timed out ({timeout:.0f}s "
                f"limit for {tier} tier).\n"
                f"   Break the task into smaller pieces, or "
                f"increase timeout in config/routing_rules.yml."
            )
            return None
        except OllamaConnectionError as e:
            state.error = f"Ollama connection failed: {e}"
            return None
        except OllamaModelError as e:
            state.error = f"Ollama model error: {e}"
            return None

    def _call_claude(
        self,
        state: AgentState,
        messages: list[dict],
        timeout: float,
    ) -> Optional[str]:
        """Call Claude API with fallback handling."""
        try:
            response = self._claude.chat(
                messages=messages,
                system_prompt=self._system_prompt,
                timeout_seconds=timeout,
            )
            return response.content

        except ClaudeTimeoutError:
            state.timed_out = True
            state.error = (
                f"⏱️  Claude API timed out ({timeout:.0f}s limit).\n"
                f"   Break the task into smaller pieces."
            )
            return None

        except (ClaudeConnectionError, ClaudeRateLimitError) as e:
            return self._handle_cloud_failure(state, str(e), messages, timeout)

        except ClaudeAuthError as e:
            state.error = (
                f"Claude API auth failed: {e}. "
                f"Check ANTHROPIC_API_KEY or use LOCAL_ONLY mode."
            )
            return None

        except ClaudeAPIError as e:
            state.error = f"Claude API error: {e}"
            return None

    def _handle_cloud_failure(
        self,
        state: AgentState,
        error_msg: str,
        messages: list[dict],
        timeout: float,
    ) -> Optional[str]:
        """
        Handle Claude API failure:
        - Security tasks: block + pending queue
        - Others: fallback to local model
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
                f"Claude API unavailable: {error_msg}\n\n"
                f"Security tasks cannot use local models "
                f"(zero-tolerance policy).\n\n"
                f"Task queued: {task_id}\n"
                f"Use '/retry {task_id}' when API recovers."
            )
            return None
        else:
            # Fallback to local
            console.print(
                "[yellow]⚠️  Claude API unavailable, "
                "falling back to local model[/yellow]"
            )
            state.model_assignment = self._resolver.resolve(
                tier=Tier.MEDIUM, is_security_task=False
            )
            fallback_timeout = self.get_timeout_for_tier(Tier.MEDIUM)
            return self._call_ollama(
                state, messages, fallback_timeout
            )

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
        self._executor.set_agent_mode(mode.value)

    @property
    def pending_count(self) -> int:
        """Number of pending tasks."""
        return self._queue.pending_count
