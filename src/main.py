"""
Hybrid AI Agent — CLI Entry Point
==================================
Interactive terminal interface with human-in-the-loop controls.

Commands:
  /mode <hybrid|local>   — Switch operation mode
  /pending               — List pending tasks
  /retry <id|all>        — Retry pending tasks
  /pending discard <id>  — Discard a pending task
  /pending clear         — Clear all pending tasks
  /health                — Show health status
  /quit                  — Exit the agent
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.router.rule_router import RuleRouter, Tier
from src.models.model_resolver import ModelResolver, AgentMode
from src.models.ollama_client import OllamaClient
from src.models.claude_client import ClaudeClient
from src.models.health_checker import HealthChecker
from src.models.pending_queue import PendingTaskQueue, PendingTask
from src.agent.graph import Agent
from src.agent.tool_executor import ToolExecutor
from src.tools.file_ops import FileOps
from src.tools.shell_exec import ShellExec
from src.tools.git_ops import GitOps
from src.tools.git_branch import GitBranchManager
from src.security.permissions import PermissionGate
from src.security.sanitizer import Sanitizer
from src.security.audit import AuditLogger


console = Console()


def create_agent() -> Agent:
    """Initialize all components and create the agent."""
    load_dotenv()

    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    primary_model = os.getenv("OLLAMA_PRIMARY_MODEL", "gemma4:26b")
    fallback_model = os.getenv("OLLAMA_FALLBACK_MODEL", "gemma4:e4b")
    claude_model = os.getenv(
        "CLAUDE_MODEL", "claude-sonnet-4-20250514"
    )
    agent_mode_str = os.getenv("AGENT_MODE", "HYBRID").upper()
    workspace = os.getenv(
        "WORKSPACE_ROOT", str(Path.cwd() / "_workspace")
    )
    audit_enabled = os.getenv(
        "AUDIT_LOG_ENABLED", "true"
    ).lower() == "true"
    max_iterations = int(os.getenv("MAX_ITERATIONS", "10"))

    try:
        agent_mode = AgentMode(agent_mode_str)
    except ValueError:
        console.print(
            f"[yellow]Warning: Unknown AGENT_MODE "
            f"'{agent_mode_str}', defaulting to HYBRID[/yellow]"
        )
        agent_mode = AgentMode.HYBRID

    # ── Initialize components ──
    router = RuleRouter(config_path="config/routing_rules.yml")
    ollama = OllamaClient(base_url=ollama_url)
    claude = ClaudeClient(model=claude_model)

    resolver = ModelResolver(
        primary_model=primary_model,
        fallback_model=fallback_model,
        cloud_model=claude_model,
        mode=agent_mode,
    )

    pending_queue = PendingTaskQueue(workspace_root=workspace)
    audit_logger = AuditLogger(
        workspace_root=workspace, enabled=audit_enabled
    )
    sanitizer = Sanitizer()

    # Security components
    permission_gate = PermissionGate(
        audit_fn=lambda action, details: audit_logger.log(
            f"permission:{action}", details, agent_mode=agent_mode.value
        )
    )

    # Tool layer
    file_ops = FileOps(workspace_root=workspace)
    shell_exec = ShellExec(workspace_root=workspace)
    git_ops = GitOps(shell=shell_exec)

    branch_manager = GitBranchManager(shell=shell_exec)

    tool_executor = ToolExecutor(
        file_ops=file_ops,
        shell_exec=shell_exec,
        git_ops=git_ops,
        permission_gate=permission_gate,
        audit_logger=audit_logger,
        agent_mode=agent_mode.value,
        branch_manager=branch_manager,
    )

    # Health checker
    def on_recovery() -> None:
        pending_count = pending_queue.pending_count
        if pending_count > 0:
            console.print(
                "\n[bold green]"
                "🔔 Claude API is back online!"
                "[/bold green]"
            )
            console.print(
                f"   You have {pending_count} pending task(s)."
            )
            console.print(
                "   Use [bold]/retry all[/bold] or "
                "[bold]/pending[/bold] to review.\n"
            )

    def on_failure(error: str) -> None:
        console.print(
            f"\n[bold yellow]⚠️  Claude API unavailable: "
            f"{error}[/bold yellow]\n"
        )

    health_checker = HealthChecker(
        check_fn=claude.is_available,
        interval_seconds=60.0,
        on_recovery=on_recovery,
        on_failure=on_failure,
    )

    agent = Agent(
        ollama_client=ollama,
        claude_client=claude,
        router=router,
        resolver=resolver,
        health_checker=health_checker,
        pending_queue=pending_queue,
        tool_executor=tool_executor,
        branch_manager=branch_manager,
        sanitizer=sanitizer,
        default_max_iterations=max_iterations,
    )

    return agent


def show_banner(agent: Agent) -> None:
    """Display startup banner."""
    mode = agent.mode.value
    mode_color = "green" if mode == "HYBRID" else "yellow"

    banner = Text()
    banner.append(
        "🤖 Hybrid AI Agent v0.2", style="bold white"
    )
    banner.append(" (ReAct Loop)\n", style="dim")
    banner.append("   Mode:     ", style="dim")
    banner.append(f"{mode}\n", style=f"bold {mode_color}")
    banner.append(
        "   Models:   Gemma4-26B | Gemma4-E4B", style="dim"
    )
    if mode == "HYBRID":
        banner.append(" | Claude API", style="dim")
    banner.append(
        "\n   Security: Zero-tolerance | Human-in-the-loop",
        style="dim",
    )
    banner.append(
        "\n   Tools:    read, write, list, search, "
        "run, delete, git",
        style="dim",
    )
    banner.append(
        "\n   Tip:      Press Ctrl+C to cancel any request",
        style="dim",
    )

    console.print(Panel(banner, border_style="blue"))


def show_disclaimer(assignment) -> bool:
    """Show security disclaimer for LOCAL_ONLY mode."""
    console.print()
    console.print(Panel(
        "[bold yellow]⚠️  SECURITY TASK — LOCAL MODEL ONLY"
        "[/bold yellow]\n\n"
        "This task involves security-sensitive analysis.\n"
        "You are running in LOCAL_ONLY mode — this response\n"
        f"is generated by [bold]{assignment.model}[/bold], "
        "NOT a frontier model.\n\n"
        "[bold]Limitations:[/bold]\n"
        "  • May miss subtle vulnerabilities\n"
        "  • Cannot match cloud model depth\n"
        "  • Should NOT be treated as a security audit\n\n"
        "[bold]Recommendation:[/bold]\n"
        "  Re-run in HYBRID mode with Claude API\n"
        "  before deploying to production.",
        title="Security Disclaimer",
        border_style="yellow",
    ))

    try:
        answer = console.input(
            "\nProceed with local analysis? [y/n]: "
        ).strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def offer_pending_queue(
    request: str, queue: PendingTaskQueue
) -> None:
    """Ask user to queue for cloud re-analysis."""
    console.print(
        "\n[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]"
    )
    console.print(
        "[yellow]⚠️  This security analysis was performed "
        "by a local model.[/yellow]"
    )

    try:
        answer = console.input(
            "   Add to pending queue for cloud re-analysis? "
            "[y/n]: "
        ).strip().lower()
        if answer in ("y", "yes"):
            task = PendingTask.create(
                original_request=request,
                classification="security",
                blocked_reason="User requested cloud re-analysis",
            )
            task_id = queue.add(task)
            console.print(
                f"   [green]Queued as {task_id}. "
                f"Use '/retry {task_id}' in HYBRID mode."
                f"[/green]"
            )
    except (EOFError, KeyboardInterrupt):
        pass


def handle_command(
    command: str, agent: Agent, queue: PendingTaskQueue
) -> bool:
    """Handle CLI commands. Returns True if handled."""
    parts = command.strip().split()
    if not parts:
        return False

    cmd = parts[0].lower()

    if cmd in ("/quit", "/exit"):
        console.print("[dim]Goodbye![/dim]")
        sys.exit(0)

    elif cmd == "/mode":
        if len(parts) < 2:
            console.print(
                f"   Current mode: [bold]{agent.mode.value}"
                f"[/bold]"
            )
            return True
        mode_str = parts[1].upper()
        if mode_str == "LOCAL":
            mode_str = "LOCAL_ONLY"
        try:
            new_mode = AgentMode(mode_str)
            agent.set_mode(new_mode)
            mode_color = (
                "green"
                if new_mode == AgentMode.HYBRID
                else "yellow"
            )
            console.print(
                f"   [bold {mode_color}]Switched to "
                f"{new_mode.value} mode."
                f"[/bold {mode_color}]"
            )
            if (
                new_mode == AgentMode.HYBRID
                and queue.pending_count > 0
            ):
                console.print(
                    f"   You have {queue.pending_count} "
                    f"pending task(s). "
                    f"Use [bold]/pending[/bold] to review."
                )
        except ValueError:
            console.print(
                f"   [red]Unknown mode: {parts[1]}. "
                f"Use 'hybrid' or 'local'.[/red]"
            )
        return True

    elif cmd == "/pending":
        if len(parts) >= 2 and parts[1] == "clear":
            count = queue.clear_all()
            console.print(f"   Cleared {count} pending task(s).")
            return True

        if len(parts) >= 3 and parts[1] == "discard":
            task_id = parts[2]
            if queue.mark_discarded(task_id):
                console.print(f"   Discarded task {task_id}.")
            else:
                console.print(
                    f"   [red]Task {task_id} not found.[/red]"
                )
            return True

        tasks = queue.list_pending()
        if not tasks:
            console.print("   No pending tasks.")
            return True

        table = Table(title="Pending Tasks")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Request", max_width=50)
        table.add_column("Reason")

        for t in tasks:
            table.add_row(
                t.task_id,
                t.classification,
                t.original_request[:50],
                t.blocked_reason[:40],
            )
        console.print(table)
        return True

    elif cmd == "/retry":
        if len(parts) < 2:
            console.print(
                "   Usage: /retry <task_id> or /retry all"
            )
            return True

        if parts[1] == "all":
            results = agent.retry_all_pending()
            if not results:
                console.print("   No pending tasks to retry.")
            for task_id, state in results:
                if state.error:
                    console.print(
                        f"   [red]{task_id}: {state.error}[/red]"
                    )
                else:
                    console.print(
                        f"   [green]{task_id}: completed[/green]"
                    )
                    console.print(state.response)
        else:
            task_id = parts[1]
            state = agent.retry_pending(task_id)
            if not state:
                console.print(
                    f"   [red]Task {task_id} not found.[/red]"
                )
            elif state.error:
                console.print(f"   [red]{state.error}[/red]")
            else:
                console.print(state.response)
        return True

    elif cmd == "/diff":
        branch_mgr = agent._branch_mgr
        if not branch_mgr or not branch_mgr.has_active_branch:
            console.print("   No active agent branch.")
            return True
        if len(parts) >= 2 and parts[1] == "summary":
            console.print(branch_mgr.get_diff_summary())
        else:
            console.print(branch_mgr.get_diff())
        return True

    elif cmd == "/apply":
        branch_mgr = agent._branch_mgr
        if not branch_mgr or not branch_mgr.has_active_branch:
            console.print("   No active agent branch to apply.")
            return True
        # Show summary before merging
        console.print(
            "[bold]Changes to merge:[/bold]"
        )
        console.print(branch_mgr.get_diff_summary())
        try:
            answer = console.input(
                "\n   Merge into "
                f"{branch_mgr.current_branch.base_branch}? "
                "[y/n]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            success, msg = branch_mgr.apply()
            if success:
                console.print(f"   [green]{msg}[/green]")
            else:
                console.print(f"   [red]{msg}[/red]")
        else:
            console.print("   [dim]Merge cancelled.[/dim]")
        return True

    elif cmd == "/discard":
        branch_mgr = agent._branch_mgr
        if not branch_mgr or not branch_mgr.has_active_branch:
            console.print(
                "   No active agent branch to discard."
            )
            return True
        branch_name = branch_mgr.current_branch.branch_name
        try:
            answer = console.input(
                f"   Discard {branch_name} and all changes? "
                "[y/n]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            success, msg = branch_mgr.discard()
            if success:
                console.print(f"   [yellow]{msg}[/yellow]")
            else:
                console.print(f"   [red]{msg}[/red]")
        else:
            console.print("   [dim]Discard cancelled.[/dim]")
        return True

    elif cmd == "/branches":
        branch_mgr = agent._branch_mgr
        if not branch_mgr:
            console.print("   Git branch manager not available.")
            return True
        branches = branch_mgr.list_agent_branches()
        if not branches:
            console.print("   No agent branches found.")
        else:
            console.print("   Agent branches:")
            for b in branches:
                active = (
                    " [green](active)[/green]"
                    if branch_mgr.has_active_branch
                    and branch_mgr.current_branch.branch_name == b
                    else ""
                )
                console.print(f"     • {b}{active}")
        return True

    elif cmd == "/health":
        status = agent._health.status
        console.print("   Claude API: ", end="")
        if status.claude_api_available:
            console.print("[bold green]Available[/bold green]")
        else:
            console.print(
                "[bold red]Unavailable[/bold red] "
                f"(failures: {status.consecutive_failures})"
            )
            if status.last_error:
                console.print(
                    f"   Last error: {status.last_error}"
                )
        console.print(
            f"   Agent mode: [bold]{agent.mode.value}[/bold]"
        )
        console.print(
            f"   Pending tasks: {agent.pending_count}"
        )
        console.print("   Timeouts:")
        for tier_name in ("SIMPLE", "MEDIUM", "COMPLEX"):
            tier = Tier(tier_name)
            t = agent.get_timeout_for_tier(tier)
            console.print(f"     {tier_name}: {t:.0f}s")
        return True

    return False


def main() -> None:
    """Main entry point."""
    agent = create_agent()
    queue = agent._queue

    agent._health.start()

    show_banner(agent)

    if not agent._ollama.is_available():
        console.print(
            "[bold red]Error: Cannot connect to Ollama. "
            "Is it running?[/bold red]"
        )
        sys.exit(1)

    primary = os.getenv("OLLAMA_PRIMARY_MODEL", "gemma4:26b")
    fallback = os.getenv("OLLAMA_FALLBACK_MODEL", "gemma4:e4b")

    for model_name in [primary, fallback]:
        if not agent._ollama.is_model_available(model_name):
            console.print(
                f"[bold red]Error: Model '{model_name}' "
                f"not found. Run 'ollama pull {model_name}' "
                f"first.[/bold red]"
            )
            sys.exit(1)

    console.print()

    # ── Main loop ──
    while True:
        try:
            user_input = console.input(
                "[bold]> [/bold]"
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if handle_command(user_input, agent, queue):
                console.print()
                continue

        # Show generating indicator
        routing = agent._router.classify(user_input)
        timeout = agent.get_timeout_for_tier(routing.tier)
        console.print(
            f"[dim][{routing.tier.value} tier → "
            f"{agent._resolver.resolve(routing.tier, routing.security_override).model}, "
            f"{timeout:.0f}s timeout, Ctrl+C to cancel][/dim]"
        )

        # Process with ReAct loop
        state = agent.process_request(user_input)

        if state.cancelled:
            console.print(
                f"\n[yellow]{state.error}[/yellow]\n"
            )
            continue

        # Handle disclaimer flow
        if (
            state.requires_disclaimer
            and not state.disclaimer_shown
        ):
            if not show_disclaimer(state.model_assignment):
                console.print(
                    "   [dim]Task cancelled.[/dim]\n"
                )
                continue
            state.disclaimer_shown = True
            console.print(
                "[dim][Generating with local model...][/dim]"
            )
            state = agent.process_request(user_input)

        # Display result
        if state.error:
            console.print(f"\n[red]{state.error}[/red]\n")
        else:
            if state.tool_calls_made:
                console.print(
                    f"[dim][Tools used: "
                    f"{', '.join(state.tool_calls_made)}]"
                    f"[/dim]"
                )
            console.print(f"\n{state.response}\n")

            if (
                state.model_assignment
                and state.model_assignment.offer_pending_queue
            ):
                offer_pending_queue(user_input, queue)
                console.print()


if __name__ == "__main__":
    main()
