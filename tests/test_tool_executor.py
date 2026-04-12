"""
Tests for Tool Executor
========================
Validates tool routing, security pipeline integration,
and git branch auto-commit behavior.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock

from src.agent.tool_interface import ToolCall
from src.agent.tool_executor import ToolExecutor
from src.tools.file_ops import FileOps
from src.tools.shell_exec import ShellExec
from src.tools.git_ops import GitOps
from src.security.permissions import PermissionGate, ApprovalDecision
from src.security.audit import AuditLogger


@pytest.fixture
def tmp_workspace():
    tmpdir = tempfile.mkdtemp(prefix="executor_test_")
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def executor(tmp_workspace: str):
    """Create executor with mocked permission gate."""
    file_ops = FileOps(workspace_root=tmp_workspace)
    shell_exec = ShellExec(workspace_root=tmp_workspace)
    git_ops = GitOps(shell=shell_exec)
    audit = AuditLogger(workspace_root=tmp_workspace, enabled=True)

    # Mock permission gate to auto-approve
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
    )


class TestReadFile:
    """read_file tool tests."""

    def test_read_existing_file(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "test.py").write_text("print('hello')")
        call = ToolCall(
            tool="read_file", params={"path": "test.py"}
        )
        result = executor.execute(call)
        assert result.success
        assert "print('hello')" in result.output

    def test_read_nonexistent_file(
        self, executor: ToolExecutor
    ) -> None:
        call = ToolCall(
            tool="read_file", params={"path": "missing.py"}
        )
        result = executor.execute(call)
        assert not result.success
        assert "not found" in result.error.lower()

    def test_read_path_traversal_blocked(
        self, executor: ToolExecutor
    ) -> None:
        call = ToolCall(
            tool="read_file",
            params={"path": "../../etc/passwd"},
        )
        result = executor.execute(call)
        assert not result.success


class TestWriteFile:
    """write_file tool tests."""

    def test_write_creates_file(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        call = ToolCall(
            tool="write_file",
            params={
                "path": "new.py",
                "content": "print('new')",
            },
        )
        result = executor.execute(call)
        assert result.success
        assert Path(tmp_workspace, "new.py").exists()

    def test_write_creates_directories(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        call = ToolCall(
            tool="write_file",
            params={
                "path": "src/deep/module.py",
                "content": "# deep module",
            },
        )
        result = executor.execute(call)
        assert result.success
        assert Path(
            tmp_workspace, "src", "deep", "module.py"
        ).exists()

    def test_write_outside_workspace_blocked(
        self, executor: ToolExecutor
    ) -> None:
        call = ToolCall(
            tool="write_file",
            params={
                "path": "/tmp/evil.py",
                "content": "bad",
            },
        )
        result = executor.execute(call)
        assert not result.success


class TestDeleteFile:
    """delete_file tool tests."""

    def test_delete_existing_file(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        target = Path(tmp_workspace, "deleteme.py")
        target.write_text("bye")
        call = ToolCall(
            tool="delete_file",
            params={
                "path": "deleteme.py",
                "reason": "No longer needed",
            },
        )
        result = executor.execute(call)
        assert result.success
        assert not target.exists()

    def test_delete_nonexistent_file(
        self, executor: ToolExecutor
    ) -> None:
        call = ToolCall(
            tool="delete_file",
            params={
                "path": "ghost.py",
                "reason": "Cleanup",
            },
        )
        result = executor.execute(call)
        assert not result.success


class TestListFiles:
    """list_files tool tests."""

    def test_list_workspace(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "a.py").write_text("")
        Path(tmp_workspace, "b.py").write_text("")
        call = ToolCall(
            tool="list_files", params={"path": "."}
        )
        result = executor.execute(call)
        assert result.success
        assert "a.py" in result.output
        assert "b.py" in result.output


class TestSearchFiles:
    """search_files tool tests."""

    def test_search_pattern(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "test_one.py").write_text("")
        Path(tmp_workspace, "test_two.py").write_text("")
        Path(tmp_workspace, "main.py").write_text("")
        call = ToolCall(
            tool="search_files",
            params={"pattern": "test_*.py"},
        )
        result = executor.execute(call)
        assert result.success
        assert "test_one.py" in result.output
        assert "test_two.py" in result.output
        assert "main.py" not in result.output


class TestRunCommand:
    """run_command tool tests."""

    def test_allowed_command_executes(
        self, executor: ToolExecutor
    ) -> None:
        # Update mock to return the actual command
        executor._permissions.approve_shell.return_value.final_command = "echo hello"
        call = ToolCall(
            tool="run_command",
            params={"command": "echo hello"},
        )
        result = executor.execute(call)
        assert result.success
        assert "hello" in result.output

    def test_blocked_command_rejected(
        self, executor: ToolExecutor
    ) -> None:
        # Blocked commands are rejected at Gate 2 (validation)
        # The mock approve_shell should return denied for blocked
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


class TestInvalidTools:
    """Invalid tool calls must be rejected."""

    def test_unknown_tool_rejected(
        self, executor: ToolExecutor
    ) -> None:
        call = ToolCall(
            tool="hack_system", params={"target": "root"}
        )
        result = executor.execute(call)
        assert not result.success
        assert "Unknown tool" in result.error

    def test_missing_params_rejected(
        self, executor: ToolExecutor
    ) -> None:
        call = ToolCall(tool="read_file", params={})
        result = executor.execute(call)
        assert not result.success
        assert "Missing required" in result.error


class TestAuditLogging:
    """Tool executions must be logged."""

    def test_read_file_logged(
        self, executor: ToolExecutor, tmp_workspace: str
    ) -> None:
        Path(tmp_workspace, "test.py").write_text("x = 1")
        call = ToolCall(
            tool="read_file", params={"path": "test.py"}
        )
        executor.execute(call)

        audit = executor._audit
        entries = audit.get_recent(1)
        assert len(entries) == 1
        assert entries[0]["event"] == "tool_execution"
        assert entries[0]["details"]["tool"] == "read_file"
