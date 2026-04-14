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
from src.agent.memory import ConversationMemory
from src.agent.scanner import WorkspaceScanner
from src.agent.background import BackgroundTaskManager, TaskStatus
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

    # Ensure .agent directory exists for persistence
    agent_dir = Path(workspace) / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

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

    auto_approve = os.getenv(
        "AUTO_APPROVE_WRITES", "false"
    ).lower() == "true"
    max_turns = int(os.getenv('MAX_CONVERSATION_TURNS', '20'))
    conversation_file = os.path.join(
        workspace, ".agent", "conversation.json"
    )
    memory = ConversationMemory(
        max_turns=max_turns,
        persist_path=conversation_file,
    )

    branch_manager = GitBranchManager(shell=shell_exec)

    workspace_scanner = WorkspaceScanner(file_ops=file_ops)

    tool_executor = ToolExecutor(
        file_ops=file_ops,
        shell_exec=shell_exec,
        git_ops=git_ops,
        permission_gate=permission_gate,
        audit_logger=audit_logger,
        agent_mode=agent_mode.value,
        branch_manager=branch_manager,
        auto_approve_writes=auto_approve,
        auto_approve_commands=auto_approve,
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
        memory=memory,
        default_max_iterations=max_iterations,
    )

    bg_manager = BackgroundTaskManager(max_concurrent=3)
    agent._scanner = workspace_scanner
    agent._bg_manager = bg_manager
    return agent


def show_banner(agent: Agent, branch_mgr) -> None:
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
    # Check git mode
    git_mode = "Branch isolation"
    if not branch_mgr or not branch_mgr.is_git_workspace:
        git_mode = "Git-unaware (no branch isolation)"
    auto_approve_status = (
        " | Auto-approve: ON"
        if agent._executor.auto_approve_writes
        else ""
    )
    git_mode += auto_approve_status
    banner.append(
        f"\n   Git:      {git_mode}",
        style="dim",
    )
    banner.append(
        "\n   Memory:   Conversation history enabled",
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
        # Cleanup: switch back to main if on agent branch
        branch_mgr = agent._branch_mgr
        if branch_mgr and branch_mgr.has_active_branch:
            branch = branch_mgr.current_branch.branch_name
            console.print(
                f"   [yellow]Active agent branch: "
                f"{branch}[/yellow]"
            )
            try:
                answer = console.input(
                    "   Apply changes before exit? "
                    "[y/n/discard]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer in ("y", "yes"):
                success, msg = branch_mgr.apply()
                console.print(
                    f"   [green]{msg}[/green]"
                    if success
                    else f"   [red]{msg}[/red]"
                )
            elif answer == "discard":
                success, msg = branch_mgr.discard()
                console.print(
                    f"   [yellow]{msg}[/yellow]"
                    if success
                    else f"   [red]{msg}[/red]"
                )
            else:
                # Leave branch as-is but switch to main
                shell = ShellExec(workspace_root=os.getenv(
                    "WORKSPACE_ROOT",
                    str(Path.cwd() / "_workspace")
                ))
                shell.execute(
                    f"git checkout "
                    f"{branch_mgr.current_branch.base_branch}"
                )
                console.print(
                    f"   [dim]Switched to main. "
                    f"Branch {branch} preserved.[/dim]"
                )
        # Save conversation before exit
        if agent._memory.has_persist_path:
            agent._memory.save()
            console.print(
                "   [dim]Conversation saved.[/dim]"
            )
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

    elif cmd == "/history":
        summary = agent._memory.get_summary()
        console.print(f"   {summary}")
        return True

    elif cmd == "/clear":
        agent._memory.clear()
        console.print(
            "   [green]Conversation history cleared "
            "(saved file removed).[/green]"
        )
        return True

    elif cmd == "/bg":
        if len(parts) < 2:
            console.print(
                "   Usage: /bg <your request>"
            )
            return True

        bg_request = " ".join(parts[1:])
        bg_mgr = agent._bg_manager

        def bg_execute(request):
            """
            Execute in background with isolated state.

            Background tasks get:
              - Own conversation memory (no pollution)
              - Silent output (no console bleed)
              - Own tool executor with auto-approve ON
                (cannot prompt for approval in background)
              - rm and pip install BLOCKED in background
              - Git branch isolation as safety net

            Note: Git branch isolation is per-task via task ID,
            so concurrent tasks create separate branches.
            """
            from src.agent.memory import ConversationMemory
            from src.agent.graph import Agent
            from src.agent.tool_executor import ToolExecutor

            # Create a background-specific tool executor
            # with auto-approve enabled (can't prompt in bg)
            bg_executor = ToolExecutor(
                file_ops=agent._executor._file_ops,
                shell_exec=agent._executor._shell,
                git_ops=agent._executor._git,
                permission_gate=agent._executor._permissions,
                audit_logger=agent._executor._audit,
                agent_mode=agent._executor._agent_mode,
                branch_manager=agent._executor._branch_mgr,
                auto_approve_writes=True,
                auto_approve_commands=True,
            )

            bg_agent = Agent(
                ollama_client=agent._ollama,
                claude_client=agent._claude,
                router=agent._router,
                resolver=agent._resolver,
                health_checker=agent._health,
                pending_queue=agent._queue,
                tool_executor=bg_executor,
                branch_manager=agent._branch_mgr,
                sanitizer=agent._sanitizer,
                memory=ConversationMemory(max_turns=20),
                silent=True,
            )
            return bg_agent.process_request(request)

        task = bg_mgr.submit(
            request=bg_request,
            execute_fn=bg_execute,
        )

        if task is None:
            console.print(
                "[red]   Maximum concurrent tasks reached "
                "(3). Wait for a task to complete or "
                "use /cancel.[/red]"
            )
        else:
            console.print(
                f"   [green][{task.task_id}] Submitted.[/green]"
            )
            console.print(
                "   Use [bold]/status[/bold] to check "
                "progress."
            )
            console.print(
                "   [dim]Background tasks auto-approve "
                "writes and safe commands. "
                "rm/pip blocked in background.[/dim]"
            )
            active = bg_mgr.active_count
            if active > 1:
                console.print(
                    f"   [dim]Note: {active} tasks running. "
                    f"Ollama processes sequentially — "
                    f"foreground requests may be slower."
                    f"[/dim]"
                )
        return True

    elif cmd == "/status":
        bg_mgr = agent._bg_manager
        tasks = bg_mgr.list_tasks()

        if not tasks:
            console.print("   No background tasks.")
            return True

        table = Table(title="Background Tasks")
        table.add_column("ID", style="cyan")
        table.add_column("Status")
        table.add_column("Elapsed")
        table.add_column("Request", max_width=45)

        status_styles = {
            TaskStatus.PENDING: "dim",
            TaskStatus.RUNNING: "yellow",
            TaskStatus.COMPLETED: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.CANCELLED: "dim red",
        }

        for t in tasks:
            style = status_styles.get(t.status, "white")
            elapsed = f"{t.elapsed_seconds:.0f}s"
            table.add_row(
                t.task_id,
                f"[{style}]{t.status.value}[/{style}]",
                elapsed,
                t.short_request,
            )
        console.print(table)
        return True

    elif cmd == "/result":
        if len(parts) < 2:
            console.print(
                "   Usage: /result <task_id>"
            )
            return True

        task_id = parts[1]
        bg_mgr = agent._bg_manager
        task = bg_mgr.get_task(task_id)

        if not task:
            console.print(
                f"   [red]Task {task_id} not found.[/red]"
            )
            return True

        if task.status == TaskStatus.RUNNING:
            console.print(
                f"   [yellow]{task_id} is still running "
                f"({task.elapsed_seconds:.0f}s elapsed)."
                f"[/yellow]"
            )
            return True

        if task.status == TaskStatus.CANCELLED:
            console.print(
                f"   [dim]{task_id} was cancelled.[/dim]"
            )
            return True

        if task.status == TaskStatus.FAILED:
            console.print(
                f"   [red]{task_id} failed: "
                f"{task.error}[/red]"
            )
            return True

        if task.result and hasattr(task.result, "response"):
            console.print(
                f"[dim][{task_id} completed in "
                f"{task.elapsed_seconds:.0f}s][/dim]"
            )
            if task.result.tool_calls_made:
                console.print(
                    f"[dim][Tools used: "
                    f"{', '.join(task.result.tool_calls_made)}"
                    f"][/dim]"
                )
            console.print(
                f"\n{task.result.response}\n"
            )
        else:
            console.print(
                f"   [dim]{task_id} completed but "
                f"no response available.[/dim]"
            )
        return True

    elif cmd == "/cancel":
        if len(parts) < 2:
            console.print(
                "   Usage: /cancel <task_id>"
            )
            return True

        task_id = parts[1]
        bg_mgr = agent._bg_manager

        if bg_mgr.cancel(task_id):
            console.print(
                f"   [yellow]{task_id} cancelled.[/yellow]"
            )
        else:
            task = bg_mgr.get_task(task_id)
            if not task:
                console.print(
                    f"   [red]Task {task_id} "
                    f"not found.[/red]"
                )
            else:
                console.print(
                    f"   [dim]{task_id} already "
                    f"{task.status.value}.[/dim]"
                )
        return True

    elif cmd == "/scan":
        # Parse scan arguments
        scan_path = "."
        scan_pattern = None
        scan_file = None
        scan_instruction = ""

        i = 1
        while i < len(parts):
            if parts[i] == "--pattern" and i + 1 < len(parts):
                scan_pattern = parts[i + 1]
                i += 2
            elif parts[i] == "--ask" and i + 1 < len(parts):
                scan_instruction = " ".join(parts[i + 1:])
                break
            else:
                target = parts[i]
                # Check if it looks like a file or directory
                if "." in target and "/" in target or target.endswith(".py"):
                    scan_file = target
                else:
                    scan_path = target
                i += 1

        console.print("[dim]Scanning workspace...[/dim]")

        scanner = agent._scanner
        scan_result = scanner.scan(
            path=scan_path,
            pattern=scan_pattern,
            specific_file=scan_file,
        )

        if scan_result.error:
            console.print(
                f"[red]Scan error: {scan_result.error}[/red]"
            )
            console.print()
            return True

        console.print(
            f"[dim]Found {scan_result.file_count} file(s), "
            f"{scan_result.total_bytes:,} bytes[/dim]"
        )
        if scan_result.truncated:
            console.print(
                "[yellow]⚠️  Content truncated — scan a "
                "specific directory for full coverage[/yellow]"
            )

        # Build prompt and send to agent
        prompt = scanner.build_analysis_prompt(
            scan_result,
            instruction=scan_instruction,
        )

        # Route and process through the agent
        routing = agent._router.classify(
            scan_instruction or "analyze code for bugs"
        )
        timeout = agent.get_timeout_for_tier(routing.tier)
        model = agent._resolver.resolve(
            routing.tier, routing.security_override
        ).model

        console.print(
            f"[dim][{routing.tier.value} tier → {model}, "
            f"{timeout:.0f}s timeout, Ctrl+C to cancel][/dim]"
        )

        state = agent.process_request(prompt)

        if state.cancelled:
            console.print(
                f"\n[yellow]{state.error}[/yellow]\n"
            )
        elif state.error:
            console.print(f"\n[red]{state.error}[/red]\n")
        else:
            console.print(f"\n{state.response}\n")

        return True

    elif cmd == "/config":
        if len(parts) < 2:
            write_status = (
                "ON" if agent._executor.auto_approve_writes
                else "OFF"
            )
            cmd_status = (
                "ON" if agent._executor.auto_approve_commands
                else "OFF"
            )
            console.print(
                f"   Auto-approve writes:   "
                f"[bold]{write_status}[/bold]"
            )
            console.print(
                f"   Auto-approve commands: "
                f"[bold]{cmd_status}[/bold]"
            )
            if write_status == "ON":
                console.print(
                    "   [dim]rm and pip install still "
                    "require manual approval[/dim]"
                )
            return True
        if len(parts) >= 3 and parts[1] == "auto-approve":
            value = parts[2].lower()
            if value in ("on", "true", "yes"):
                agent._executor.set_auto_approve(True)
                if agent._executor.auto_approve_writes:
                    console.print(
                        "   [green]Auto-approve writes: ON[/green]"
                    )
                    console.print(
                        "   [dim]File writes auto-approved. "
                        "Git branch is your safety net.[/dim]"
                    )
            elif value in ("off", "false", "no"):
                agent._executor.set_auto_approve(False)
                console.print(
                    "   [yellow]Auto-approve writes: OFF[/yellow]"
                )
            else:
                console.print(
                    "   [red]Usage: /config auto-approve "
                    "on|off[/red]"
                )
            return True
        console.print(
            "   [red]Unknown config. "
            "Available: auto-approve[/red]"
        )
        return True

    elif cmd == "/save":
        if agent._memory.save():
            console.print(
                "   [green]Conversation saved.[/green]"
            )
        else:
            console.print(
                "   [red]Failed to save conversation.[/red]"
            )
        return True

    elif cmd == "/load":
        if agent._memory.load():
            console.print(
                f"   [green]Loaded {agent._memory.turn_count} "
                f"turns from saved session.[/green]"
            )
        else:
            console.print(
                "   [dim]No saved conversation found.[/dim]"
            )
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
    branch_mgr = agent._branch_mgr

    show_banner(agent, branch_mgr)

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

    # Load previous conversation if exists
    if agent._memory.load():
        console.print(
            f"[dim]Loaded {agent._memory.turn_count} turns "
            f"from previous session.[/dim]"
        )

    # Check git health in workspace
    branch_mgr = agent._branch_mgr
    if branch_mgr:
        healthy, git_msg = branch_mgr.verify_git_health()
        if not healthy:
            console.print(
                f"[bold yellow]⚠️  Git warning: "
                f"{git_msg}[/bold yellow]"
            )
        elif "orphaned" in git_msg.lower():
            console.print(
                f"[yellow]ℹ️  {git_msg}[/yellow]"
            )

    console.print()

    # ── Main loop ──
    while True:
        try:
            user_input = console.input(
                "[bold]> [/bold]"
            ).strip()
        except (EOFError, KeyboardInterrupt):
            # Save conversation before exit
            if agent._memory.has_persist_path:
                agent._memory.save()
                console.print(
                    "\n   [dim]Conversation saved.[/dim]"
                )
            console.print("[dim]Goodbye![/dim]")
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

        # Warn if background tasks are active (Ollama queues requests)
        bg_active = agent._bg_manager.active_count
        if bg_active > 0:
            console.print(
                f"[yellow]ℹ️  {bg_active} background task(s) "
                f"running — Ollama queues requests, "
                f"response may be slower[/yellow]"
            )
            # Extend timeout to account for queue wait
            timeout = timeout + (bg_active * 60)
        console.print(
            f"[dim][{routing.tier.value} tier → "
            f"{agent._resolver.resolve(routing.tier, routing.security_override).model}, "
            f"{timeout:.0f}s timeout, Ctrl+C to cancel][/dim]"
        )

        # Process with ReAct loop
        state = agent.process_request(
            user_input, timeout_override=timeout
        )

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
