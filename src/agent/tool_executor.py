"""
Tool Executor
==============
Bridges the LLM's tool calls to the actual tool implementations.

Takes a parsed ToolCall, routes it to the appropriate tool
(FileOps, ShellExec, GitOps), enforces security gates,
and returns a ToolResult.

Security design:
  - All file operations go through FileOps (path validation)
  - All shell commands go through ShellExec (three-gate validation)
  - All write/delete/exec operations require human approval
  - Tool names validated against registry before execution
  - Audit logging for every tool execution
"""

from __future__ import annotations

import time

from src.agent.tool_interface import (
    ToolCall,
    ToolResult,
    validate_tool_call,
)
from src.tools.file_ops import FileOps
from src.tools.shell_exec import ShellExec
from src.tools.git_ops import GitOps
from src.security.permissions import PermissionGate
from src.security.audit import AuditLogger


class ToolExecutor:
    """
    Executes validated tool calls through the security pipeline.

    Each tool call goes through:
      1. Registry validation (is this a real tool?)
      2. Tool-specific execution with security checks
      3. Human approval for side-effecting operations
      4. Audit logging
    """

    def __init__(
        self,
        file_ops: FileOps,
        shell_exec: ShellExec,
        git_ops: GitOps,
        permission_gate: PermissionGate,
        audit_logger: AuditLogger,
        agent_mode: str = "HYBRID",
    ) -> None:
        self._file_ops = file_ops
        self._shell = shell_exec
        self._git = git_ops
        self._permissions = permission_gate
        self._audit = audit_logger
        self._agent_mode = agent_mode

    def set_agent_mode(self, mode: str) -> None:
        """Update agent mode for audit logging."""
        self._agent_mode = mode

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a tool call through the security pipeline.

        Args:
            tool_call: Parsed and validated tool call.

        Returns:
            ToolResult with output or error.
        """
        # Validate against registry
        error = validate_tool_call(tool_call)
        if error:
            return ToolResult(
                tool=tool_call.tool,
                success=False,
                output="",
                error=error,
            )

        start_time = time.time()

        # Route to appropriate handler
        handlers = {
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "list_files": self._handle_list_files,
            "search_files": self._handle_search_files,
            "run_command": self._handle_run_command,
            "delete_file": self._handle_delete_file,
            "git_status": self._handle_git_status,
            "git_diff": self._handle_git_diff,
        }

        handler = handlers.get(tool_call.tool)
        if not handler:
            return ToolResult(
                tool=tool_call.tool,
                success=False,
                output="",
                error=f"No handler for tool: {tool_call.tool}",
            )

        result = handler(tool_call)

        # Audit log
        duration_ms = (time.time() - start_time) * 1000
        self._audit.log_tool_execution(
            tool=tool_call.tool,
            command=str(tool_call.params),
            success=result.success,
            duration_ms=duration_ms,
            agent_mode=self._agent_mode,
        )

        return result

    # ── File Operations ──

    def _handle_read_file(self, call: ToolCall) -> ToolResult:
        """Read a file — no approval needed."""
        path = call.params.get("path", "")
        result = self._file_ops.read(path)

        if result.success:
            return ToolResult(
                tool="read_file",
                success=True,
                output=result.content or "",
            )
        return ToolResult(
            tool="read_file",
            success=False,
            output="",
            error=result.error or "Unknown read error",
        )

    def _handle_write_file(self, call: ToolCall) -> ToolResult:
        """Write a file — requires human approval."""
        path = call.params.get("path", "")
        content = call.params.get("content", "")

        # Prepare the write (validates path, doesn't write yet)
        prep_result = self._file_ops.write(path, content)
        if not prep_result.success:
            return ToolResult(
                tool="write_file",
                success=False,
                output="",
                error=prep_result.error or "Write preparation failed",
            )

        # Request human approval
        approval = self._permissions.approve_file_write(
            prep_result,
            agent_reason=f"Writing {len(content)} bytes to {path}",
        )

        self._audit.log_approval(
            action="write_file",
            command=f"write:{path}",
            decision=approval.decision.value,
            agent_mode=self._agent_mode,
        )

        if not approval.is_approved:
            return ToolResult(
                tool="write_file",
                success=False,
                output="",
                error="Write denied by user.",
            )

        # Execute the write
        exec_result = self._file_ops.execute_write(path, content)
        if exec_result.success:
            return ToolResult(
                tool="write_file",
                success=True,
                output=f"File written: {path} ({exec_result.file_size_bytes} bytes)",
            )
        return ToolResult(
            tool="write_file",
            success=False,
            output="",
            error=exec_result.error or "Write execution failed",
        )

    def _handle_list_files(self, call: ToolCall) -> ToolResult:
        """List files — no approval needed."""
        path = call.params.get("path", ".")
        recursive = call.params.get("recursive", False)

        result = self._file_ops.list_dir(path, recursive=recursive)
        if result.success:
            return ToolResult(
                tool="list_files",
                success=True,
                output=result.content or "Empty directory.",
            )
        return ToolResult(
            tool="list_files",
            success=False,
            output="",
            error=result.error or "List failed",
        )

    def _handle_search_files(self, call: ToolCall) -> ToolResult:
        """Search files — no approval needed."""
        pattern = call.params.get("pattern", "")
        path = call.params.get("path", ".")

        result = self._file_ops.search(pattern, path)
        if result.success:
            return ToolResult(
                tool="search_files",
                success=True,
                output=result.content or "No files found.",
            )
        return ToolResult(
            tool="search_files",
            success=False,
            output="",
            error=result.error or "Search failed",
        )

    def _handle_delete_file(self, call: ToolCall) -> ToolResult:
        """Delete a file — requires human approval with justification."""
        path = call.params.get("path", "")
        reason = call.params.get("reason", "")

        # Prepare the delete (validates path)
        prep_result = self._file_ops.delete(path)
        if not prep_result.success:
            return ToolResult(
                tool="delete_file",
                success=False,
                output="",
                error=prep_result.error or "Delete preparation failed",
            )

        # Request human approval
        approval = self._permissions.approve_file_delete(
            prep_result,
            agent_reason=reason,
        )

        self._audit.log_approval(
            action="delete_file",
            command=f"delete:{path}",
            decision=approval.decision.value,
            agent_mode=self._agent_mode,
        )

        if not approval.is_approved:
            return ToolResult(
                tool="delete_file",
                success=False,
                output="",
                error="Delete denied by user.",
            )

        # Execute the delete
        exec_result = self._file_ops.execute_delete(path)
        if exec_result.success:
            return ToolResult(
                tool="delete_file",
                success=True,
                output=f"File deleted: {path}",
            )
        return ToolResult(
            tool="delete_file",
            success=False,
            output="",
            error=exec_result.error or "Delete execution failed",
        )

    # ── Shell Execution ──

    def _handle_run_command(self, call: ToolCall) -> ToolResult:
        """Run a shell command — three-gate validation + approval."""
        command = call.params.get("command", "")

        # Gate 1 + 2: Validate
        validation = self._shell.validate(command)

        # Gate 3: Human approval
        approval = self._permissions.approve_shell(
            validation,
            agent_reason=f"Agent requested: {command}",
        )

        self._audit.log_approval(
            action="run_command",
            command=command,
            decision=approval.decision.value,
            risk_level=validation.risk_level.value,
            agent_mode=self._agent_mode,
        )

        if not approval.is_approved:
            return ToolResult(
                tool="run_command",
                success=False,
                output="",
                error=approval.reason or "Command denied.",
            )

        # Execute the approved (possibly edited) command
        final_command = approval.final_command
        shell_result = self._shell.execute(final_command)

        if shell_result.success:
            output = shell_result.stdout
            if shell_result.stderr:
                output += f"\n[stderr]\n{shell_result.stderr}"
            return ToolResult(
                tool="run_command",
                success=True,
                output=output or "(no output)",
            )

        error_msg = shell_result.error or shell_result.stderr
        if shell_result.timed_out:
            error_msg = f"Command timed out: {error_msg}"
        return ToolResult(
            tool="run_command",
            success=False,
            output=shell_result.stdout or "",
            error=error_msg or f"Exit code: {shell_result.exit_code}",
        )

    # ── Git Operations ──

    def _handle_git_status(self, call: ToolCall) -> ToolResult:
        """Git status — no approval needed (read-only)."""
        result = self._git.status()
        if result.success:
            parsed = self._git.parse_status(result.stdout)
            return ToolResult(
                tool="git_status",
                success=True,
                output=parsed.summary + "\n\n" + result.stdout,
            )
        return ToolResult(
            tool="git_status",
            success=False,
            output="",
            error=result.error or result.stderr or "Git status failed",
        )

    def _handle_git_diff(self, call: ToolCall) -> ToolResult:
        """Git diff — no approval needed (read-only)."""
        path = call.params.get("path")
        diff_cmd = self._git.diff(path)

        # Validate through shell (even read-only git commands)
        validation = self._shell.validate(diff_cmd)
        if not validation.is_allowed:
            return ToolResult(
                tool="git_diff",
                success=False,
                output="",
                error=validation.reason,
            )

        result = self._shell.execute(diff_cmd)
        if result.success:
            output = result.stdout or "(no changes)"
            return ToolResult(
                tool="git_diff",
                success=True,
                output=output,
            )
        return ToolResult(
            tool="git_diff",
            success=False,
            output="",
            error=result.error or result.stderr or "Git diff failed",
        )
