"""
Tests for Auto-Approve Feature
================================
Validates auto-approve behavior for file writes and commands,
safety constraints, and git requirement enforcement.
"""

import pytest
import tempfile
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from src.agent.tool_interface import ToolCall
from src.agent.tool_executor import ToolExecutor
from src.tools.file_ops import FileOps
from src.tools.shell_exec import ShellExec
from src.tools.git_ops import GitOps
from src.tools.git_branch import GitBranchManager
from src.security.permissions import PermissionGate, ApprovalDecision
from src.security.audit import AuditLogger


@pytest.fixture
def git_workspace():
    """Workspace with git initialized."""
    tmpdir = tempfile.mkdtemp(prefix="auto_test_")
    subprocess.run(
        ["git", "init"], cwd=tmpdir, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmpdir, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmpdir, capture_output=True,
    )
    Path(tmpdir, "README.md").write_text("# Test")
    subprocess.run(
        ["git", "add", "."], cwd=tmpdir, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmpdir, capture_output=True,
    )
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def no_git_workspace():
    """Workspace without git."""
    tmpdir = tempfile.mkdtemp(prefix="auto_nogit_")
    yield tmpdir
    shutil.rmtree(tmpdir)


def make_executor(
    workspace: str,
    auto_writes: bool = False,
    auto_commands: bool = False,
) -> ToolExecutor:
    """Create executor with configurable auto-approve."""
    file_ops = FileOps(workspace_root=workspace)
    shell_exec = ShellExec(workspace_root=workspace)
    git_ops = GitOps(shell=shell_exec)
    branch_mgr = GitBranchManager(shell=shell_exec)
    audit = AuditLogger(workspace_root=workspace, enabled=True)

    gate = MagicMock(spec=PermissionGate)
    mock_approval = MagicMock()
    mock_approval.is_approved = True
    mock_approval.decision = ApprovalDecision.APPROVED
    mock_approval.final_command = ""
    gate.approve_file_write.return_value = mock_approval
    gate.approve_file_delete.return_value = mock_approval
    gate.approve_shell.return_value = mock_approval

    return ToolExecutor(
        file_ops=file_ops,
        shell_exec=shell_exec,
        git_ops=git_ops,
        permission_gate=gate,
        audit_logger=audit,
        branch_manager=branch_mgr,
        auto_approve_writes=auto_writes,
        auto_approve_commands=auto_commands,
    )


class TestAutoApproveWrites:
    """Auto-approve file write behavior."""

    def test_auto_approve_skips_permission_gate(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_writes=True
        )
        call = ToolCall(
            tool="write_file",
            params={"path": "test.py", "content": "x = 1"},
        )
        result = executor.execute(call)
        assert result.success
        # Permission gate should NOT have been called
        executor._permissions.approve_file_write.assert_not_called()

    def test_auto_approve_off_calls_permission_gate(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_writes=False
        )
        call = ToolCall(
            tool="write_file",
            params={"path": "test.py", "content": "x = 1"},
        )
        executor.execute(call)
        # Permission gate SHOULD have been called
        executor._permissions.approve_file_write.assert_called_once()

    def test_auto_approve_creates_file(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_writes=True
        )
        call = ToolCall(
            tool="write_file",
            params={"path": "new.py", "content": "print('hi')"},
        )
        result = executor.execute(call)
        assert result.success
        assert Path(git_workspace, "new.py").exists()


class TestAutoApproveCommands:
    """Auto-approve shell command behavior."""

    def test_auto_approve_runs_safe_command(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_commands=True
        )
        # Use ls which is in the allowed list
        call = ToolCall(
            tool="run_command",
            params={"command": "ls"},
        )
        result = executor.execute(call)
        assert result.success
        # ls should list files (at least README.md from fixture)
        assert "README" in result.output

    def test_rm_always_requires_approval(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace,
            auto_writes=True,
            auto_commands=True,
        )
        Path(git_workspace, "delete_me.py").write_text("bye")
        call = ToolCall(
            tool="delete_file",
            params={
                "path": "delete_me.py",
                "reason": "cleanup",
            },
        )
        executor.execute(call)
        # Delete should still go through permission gate
        executor._permissions.approve_file_delete.assert_called_once()

    def test_pip_install_always_requires_approval(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_commands=True
        )
        call = ToolCall(
            tool="run_command",
            params={"command": "pip install requests"},
        )
        executor.execute(call)
        # pip install should still go through permission gate
        executor._permissions.approve_shell.assert_called_once()

    def test_blocked_command_still_blocked(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_commands=True
        )
        # curl is blocked at Gate 2 — mock deny for blocked commands
        from src.security.permissions import ApprovalResult, ApprovalDecision
        denied = ApprovalResult(
            decision=ApprovalDecision.DENIED,
            original_command="curl http://evil.com",
            reason="Blocked by policy",
        )
        executor._permissions.approve_shell.return_value = denied

        call = ToolCall(
            tool="run_command",
            params={"command": "curl http://evil.com"},
        )
        result = executor.execute(call)
        assert not result.success


class TestAutoApproveRequiresGit:
    """Auto-approve must be blocked without git."""

    def test_cannot_enable_without_git(
        self, no_git_workspace: str
    ) -> None:
        executor = make_executor(
            no_git_workspace, auto_writes=False
        )
        executor.set_auto_approve(True)
        # Should remain off because no git repo
        assert not executor.auto_approve_writes

    def test_works_with_git(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_writes=False
        )
        executor.set_auto_approve(True)
        assert executor.auto_approve_writes
        assert executor.auto_approve_commands


class TestAutoApproveAudit:
    """Auto-approved actions must be logged."""

    def test_auto_write_logged(
        self, git_workspace: str
    ) -> None:
        executor = make_executor(
            git_workspace, auto_writes=True
        )
        call = ToolCall(
            tool="write_file",
            params={"path": "logged.py", "content": "x = 1"},
        )
        executor.execute(call)

        entries = executor._audit.get_recent(5)
        approval_entries = [
            e for e in entries
            if e["event"] == "approval"
        ]
        assert len(approval_entries) >= 1
        assert any(
            e["details"]["decision"] == "AUTO_APPROVED"
            for e in approval_entries
        )
