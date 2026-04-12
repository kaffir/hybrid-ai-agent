"""
Tests for Git Branch Isolation
================================
Validates branch creation, auto-commit, merge, discard,
and git-unaware mode.
"""

import pytest
import tempfile
import shutil
import subprocess
from pathlib import Path

from src.tools.shell_exec import ShellExec
from src.tools.git_branch import GitBranchManager


@pytest.fixture
def git_workspace():
    """Create a temporary workspace with git initialized."""
    tmpdir = tempfile.mkdtemp(prefix="git_test_")
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
    # Create initial commit
    Path(tmpdir, "README.md").write_text("# Test")
    subprocess.run(
        ["git", "add", "."], cwd=tmpdir, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmpdir, capture_output=True,
    )
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def no_git_workspace():
    """Create a temporary workspace WITHOUT git."""
    tmpdir = tempfile.mkdtemp(prefix="nogit_test_")
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def branch_mgr(git_workspace: str) -> GitBranchManager:
    shell = ShellExec(workspace_root=git_workspace)
    return GitBranchManager(shell=shell)


@pytest.fixture
def no_git_branch_mgr(
    no_git_workspace: str,
) -> GitBranchManager:
    shell = ShellExec(workspace_root=no_git_workspace)
    return GitBranchManager(shell=shell)


class TestGitAwareDetection:
    """Agent must detect git vs non-git workspaces."""

    def test_detects_git_workspace(
        self, branch_mgr: GitBranchManager
    ) -> None:
        assert branch_mgr.is_git_workspace

    def test_detects_non_git_workspace(
        self, no_git_branch_mgr: GitBranchManager
    ) -> None:
        assert not no_git_branch_mgr.is_git_workspace

    def test_non_git_start_task_returns_none(
        self, no_git_branch_mgr: GitBranchManager
    ) -> None:
        result = no_git_branch_mgr.start_task()
        assert result is None

    def test_non_git_has_no_active_branch(
        self, no_git_branch_mgr: GitBranchManager
    ) -> None:
        assert not no_git_branch_mgr.has_active_branch


class TestBranchCreation:
    """Branch creation and checkout."""

    def test_creates_agent_branch(
        self, branch_mgr: GitBranchManager
    ) -> None:
        info = branch_mgr.start_task("test123")
        assert info is not None
        assert info.branch_name == "agent/task-test123"
        assert info.is_agent_branch
        assert info.active

    def test_auto_generates_task_id(
        self, branch_mgr: GitBranchManager
    ) -> None:
        info = branch_mgr.start_task()
        assert info is not None
        assert info.branch_name.startswith("agent/task-")
        assert len(info.task_id) == 8

    def test_tracks_base_branch(
        self, branch_mgr: GitBranchManager
    ) -> None:
        info = branch_mgr.start_task()
        assert info is not None
        # Base should be main or master
        assert info.base_branch in ("main", "master")


class TestAutoCommit:
    """Auto-commit on file changes."""

    def test_commit_increments_counter(
        self, branch_mgr: GitBranchManager, git_workspace: str
    ) -> None:
        branch_mgr.start_task("commit-test")
        Path(git_workspace, "new.py").write_text("x = 1")
        success = branch_mgr.commit_change(
            "Added new.py", files=["new.py"]
        )
        assert success
        assert branch_mgr.current_branch.commits == 1

    def test_multiple_commits(
        self, branch_mgr: GitBranchManager, git_workspace: str
    ) -> None:
        branch_mgr.start_task("multi-commit")
        for i in range(3):
            Path(git_workspace, f"file{i}.py").write_text(
                f"x = {i}"
            )
            branch_mgr.commit_change(
                f"Added file{i}.py", files=[f"file{i}.py"]
            )
        assert branch_mgr.current_branch.commits == 3

    def test_commit_without_active_branch_fails(
        self, branch_mgr: GitBranchManager
    ) -> None:
        success = branch_mgr.commit_change("No branch")
        assert not success


class TestDiff:
    """Diff between agent branch and base."""

    def test_diff_shows_changes(
        self, branch_mgr: GitBranchManager, git_workspace: str
    ) -> None:
        branch_mgr.start_task("diff-test")
        Path(git_workspace, "change.py").write_text("new code")
        branch_mgr.commit_change(
            "Added change.py", files=["change.py"]
        )
        diff = branch_mgr.get_diff()
        assert "change.py" in diff
        assert "new code" in diff

    def test_diff_summary(
        self, branch_mgr: GitBranchManager, git_workspace: str
    ) -> None:
        branch_mgr.start_task("summary-test")
        Path(git_workspace, "file.py").write_text("code")
        branch_mgr.commit_change(
            "Added file.py", files=["file.py"]
        )
        summary = branch_mgr.get_diff_summary()
        assert "file.py" in summary

    def test_diff_no_active_branch(
        self, branch_mgr: GitBranchManager
    ) -> None:
        diff = branch_mgr.get_diff()
        assert "No active" in diff


class TestApply:
    """Merging agent branch into base."""

    def test_apply_merges_to_base(
        self, branch_mgr: GitBranchManager, git_workspace: str
    ) -> None:
        branch_mgr.start_task("apply-test")
        Path(git_workspace, "merged.py").write_text("merged")
        branch_mgr.commit_change(
            "Added merged.py", files=["merged.py"]
        )

        success, msg = branch_mgr.apply()
        assert success
        assert "Merged" in msg
        assert not branch_mgr.has_active_branch

        # File should exist on main
        assert Path(git_workspace, "merged.py").exists()

    def test_apply_no_active_branch(
        self, branch_mgr: GitBranchManager
    ) -> None:
        success, msg = branch_mgr.apply()
        assert not success


class TestDiscard:
    """Discarding agent branch."""

    def test_discard_removes_branch(
        self, branch_mgr: GitBranchManager, git_workspace: str
    ) -> None:
        branch_mgr.start_task("discard-test")
        Path(git_workspace, "temp.py").write_text("temp")
        branch_mgr.commit_change(
            "Added temp.py", files=["temp.py"]
        )

        success, msg = branch_mgr.discard()
        assert success
        assert "Discarded" in msg
        assert not branch_mgr.has_active_branch

        # File should NOT exist on main
        assert not Path(git_workspace, "temp.py").exists()

    def test_discard_no_active_branch(
        self, branch_mgr: GitBranchManager
    ) -> None:
        success, msg = branch_mgr.discard()
        assert not success


class TestListBranches:
    """Listing agent branches."""

    def test_list_empty(
        self, branch_mgr: GitBranchManager
    ) -> None:
        branches = branch_mgr.list_agent_branches()
        assert len(branches) == 0

    def test_list_active_branch(
        self, branch_mgr: GitBranchManager
    ) -> None:
        branch_mgr.start_task("list-test")
        branches = branch_mgr.list_agent_branches()
        assert len(branches) == 1
        assert "agent/task-list-test" in branches[0]


class TestHealthCheck:
    """Git health verification."""

    def test_healthy_repo(
        self, branch_mgr: GitBranchManager
    ) -> None:
        healthy, msg = branch_mgr.verify_git_health()
        assert healthy

    def test_non_git_workspace_reports_unaware(
        self, no_git_branch_mgr: GitBranchManager
    ) -> None:
        healthy, msg = no_git_branch_mgr.verify_git_health()
        assert healthy
        assert "git-unaware" in msg.lower()
