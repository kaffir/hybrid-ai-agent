"""
Human-in-the-Loop Permission Layer
====================================
Gate 3 of the security pipeline. Every write operation,
shell command, and file deletion requires explicit human
approval before execution.

Security design:
  - All approvals are interactive (stdin) — no auto-approve
  - Risk level displayed with visual indicators
  - Enhanced approval for rm (justification required)
  - Enhanced approval for pip install (security assessment required)
  - Edit option allows modifying commands before execution
  - All decisions are logged via audit module
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

from rich.console import Console
from rich.panel import Panel

from src.tools.shell_exec import CommandValidation, RiskLevel
from src.tools.file_ops import FileOpResult


console = Console()


class ApprovalDecision(str, Enum):
    """User's approval decision."""

    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EDITED = "EDITED"
    CANCELLED = "CANCELLED"


@dataclass
class ApprovalResult:
    """Result of an approval request."""

    decision: ApprovalDecision
    original_command: str = ""
    edited_command: Optional[str] = None
    reason: Optional[str] = None

    @property
    def is_approved(self) -> bool:
        return self.decision in (
            ApprovalDecision.APPROVED,
            ApprovalDecision.EDITED,
        )

    @property
    def final_command(self) -> str:
        if self.decision == ApprovalDecision.EDITED and self.edited_command:
            return self.edited_command
        return self.original_command


_RISK_INDICATORS = {
    RiskLevel.LOW: ("🟢", "LOW", "green"),
    RiskLevel.MEDIUM: ("🟡", "MEDIUM", "yellow"),
    RiskLevel.HIGH: ("🟠", "HIGH", "red"),
    RiskLevel.BLOCKED: ("🔴", "BLOCKED", "red bold"),
}


class PermissionGate:
    """
    Interactive permission gate for tool operations.

    Presents approval prompts to the user with risk
    classification and context.
    """

    def __init__(
        self,
        audit_fn: Optional[Callable] = None,
    ) -> None:
        """
        Args:
            audit_fn: Optional callback to log approval decisions.
                      Signature: audit_fn(action, details)
        """
        self._audit_fn = audit_fn

    def _log(self, action: str, details: dict) -> None:
        """Log approval decision if audit function is set."""
        if self._audit_fn:
            self._audit_fn(action, details)

    # ── Shell Command Approval ──

    def approve_shell(
        self,
        validation: CommandValidation,
        agent_reason: str = "",
    ) -> ApprovalResult:
        """
        Request human approval for a shell command.

        Args:
            validation: Gate 1+2 validation result.
            agent_reason: Why the agent wants to run this command.

        Returns:
            ApprovalResult with user's decision.
        """
        if not validation.is_allowed:
            console.print(
                "\n[red bold]⛔ COMMAND BLOCKED[/red bold]"
            )
            console.print(f"   Command:  {validation.command}")
            console.print(f"   Reason:   {validation.reason}")
            console.print(f"   Gate:     {validation.blocked_by}\n")
            self._log("shell_blocked", {
                "command": validation.command,
                "reason": validation.reason,
                "blocked_by": validation.blocked_by,
            })
            return ApprovalResult(
                decision=ApprovalDecision.DENIED,
                original_command=validation.command,
                reason=validation.reason,
            )

        # Enhanced approval: rm
        if validation.enhanced_approval_type == "rm":
            return self._approve_rm(validation, agent_reason)

        # Enhanced approval: pip install
        if validation.enhanced_approval_type == "pip":
            return self._approve_pip(validation, agent_reason)

        # Standard approval
        return self._approve_standard(validation, agent_reason)

    def _approve_standard(
        self,
        validation: CommandValidation,
        agent_reason: str,
    ) -> ApprovalResult:
        """Standard shell command approval prompt."""
        icon, level, color = _RISK_INDICATORS.get(
            validation.risk_level, ("⚪", "UNKNOWN", "white")
        )

        console.print()
        console.print(
            Panel(
                f"[bold]Command:[/bold]  {validation.command}\n"
                f"[bold]Risk:[/bold]     {icon} [{color}]{level}[/{color}]"
                + (f"\n[bold]Reason:[/bold]   {agent_reason}" if agent_reason else ""),
                title="Shell Execution Request",
                border_style="blue",
            )
        )

        return self._prompt_decision(validation.command)

    def _approve_rm(
        self,
        validation: CommandValidation,
        agent_reason: str,
    ) -> ApprovalResult:
        """Enhanced approval for file deletion."""
        console.print()
        console.print(
            Panel(
                f"[bold]Command:[/bold]  {validation.command}\n"
                f"[bold]Risk:[/bold]     🟠 [red]HIGH — file deletion[/red]\n"
                f"[bold]Reason:[/bold]   {agent_reason or 'No reason provided'}\n"
                f"\n"
                f"[dim]Note: Verify the file is tracked by git for recovery.[/dim]",
                title="⚠️  File Deletion Request",
                border_style="yellow",
            )
        )

        if not agent_reason:
            console.print(
                "   [yellow]Warning: Agent did not provide a reason "
                "for deletion.[/yellow]"
            )

        return self._prompt_decision(validation.command)

    def _approve_pip(
        self,
        validation: CommandValidation,
        agent_reason: str,
    ) -> ApprovalResult:
        """Enhanced approval for pip install with security assessment."""
        console.print()
        console.print(
            Panel(
                f"[bold]Command:[/bold]     {validation.command}\n"
                f"[bold]Risk:[/bold]        🟠 [red]HIGH — package installation[/red]\n"
                f"\n"
                f"[bold]Assessment:[/bold]\n"
                f"{agent_reason or 'No assessment provided.'}\n"
                f"\n"
                f"[dim italic]ⓘ  This assessment is AI-generated. "
                f"Verify security claims independently "
                f"for unfamiliar packages.[/dim italic]",
                title="⚠️  Package Installation Request",
                border_style="yellow",
            )
        )

        return self._prompt_decision(validation.command)

    # ── File Operation Approval ──

    def approve_file_write(
        self,
        result: FileOpResult,
        agent_reason: str = "",
    ) -> ApprovalResult:
        """
        Request approval for a file write operation.

        Shows a preview of the content to be written.
        """
        # Truncate preview for very large files
        preview = result.content or ""
        if len(preview) > 2000:
            preview = preview[:1000] + "\n\n... (truncated) ...\n\n" + preview[-500:]

        size_kb = result.file_size_bytes / 1024

        console.print()
        console.print(
            Panel(
                f"[bold]Action:[/bold]   CREATE/OVERWRITE file\n"
                f"[bold]Path:[/bold]     {result.path}\n"
                f"[bold]Size:[/bold]     {size_kb:.1f} KB\n"
                f"[bold]Risk:[/bold]     🟡 [yellow]MEDIUM — file write[/yellow]"
                + (f"\n[bold]Reason:[/bold]   {agent_reason}" if agent_reason else ""),
                title="File Write Request",
                border_style="blue",
            )
        )

        # Show content preview
        console.print("[dim]--- Preview ---[/dim]")
        console.print(preview)
        console.print("[dim]--- End Preview ---[/dim]")

        return self._prompt_decision(f"write:{result.path}")

    def approve_file_delete(
        self,
        result: FileOpResult,
        agent_reason: str = "",
        is_git_tracked: bool = False,
    ) -> ApprovalResult:
        """Request approval for file deletion."""
        size_kb = result.file_size_bytes / 1024
        reversible = "yes (git tracked)" if is_git_tracked else "⚠️  NO — not recoverable"

        console.print()
        console.print(
            Panel(
                f"[bold]Action:[/bold]       DELETE file\n"
                f"[bold]Path:[/bold]         {result.path}\n"
                f"[bold]Size:[/bold]         {size_kb:.1f} KB\n"
                f"[bold]Risk:[/bold]         🟠 [red]HIGH — file deletion[/red]\n"
                f"[bold]Reason:[/bold]       {agent_reason or 'No reason provided'}\n"
                f"[bold]Reversible:[/bold]   {reversible}",
                title="⚠️  File Deletion Request",
                border_style="yellow",
            )
        )

        return self._prompt_decision(f"delete:{result.path}")

    # ── Common Prompt ──

    def _prompt_decision(self, command: str) -> ApprovalResult:
        """
        Show approve/deny/edit prompt and return decision.

        Returns:
            ApprovalResult with user's choice.
        """
        try:
            answer = console.input(
                "\n[bold]  [green]approve[/green] / "
                "[red]deny[/red] / "
                "[yellow]edit[/yellow]  [/bold] → "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            self._log("approval_cancelled", {"command": command})
            return ApprovalResult(
                decision=ApprovalDecision.CANCELLED,
                original_command=command,
            )

        if answer in ("a", "approve", "y", "yes"):
            self._log("approved", {"command": command})
            return ApprovalResult(
                decision=ApprovalDecision.APPROVED,
                original_command=command,
            )
        elif answer in ("e", "edit"):
            return self._handle_edit(command)
        else:
            self._log("denied", {"command": command})
            return ApprovalResult(
                decision=ApprovalDecision.DENIED,
                original_command=command,
                reason=f"User denied: {answer}",
            )

    def _handle_edit(self, original_command: str) -> ApprovalResult:
        """Allow user to edit a command before approval."""
        try:
            console.print(f"   [dim]Original: {original_command}[/dim]")
            edited = console.input("   [yellow]Edit → [/yellow]").strip()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult(
                decision=ApprovalDecision.CANCELLED,
                original_command=original_command,
            )

        if not edited:
            console.print("   [dim]No changes — using original.[/dim]")
            self._log("approved_no_edit", {"command": original_command})
            return ApprovalResult(
                decision=ApprovalDecision.APPROVED,
                original_command=original_command,
            )

        console.print(f"   [green]Updated to: {edited}[/green]")
        self._log("approved_edited", {
            "original": original_command,
            "edited": edited,
        })
        return ApprovalResult(
            decision=ApprovalDecision.EDITED,
            original_command=original_command,
            edited_command=edited,
        )
