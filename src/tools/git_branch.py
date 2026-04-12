"""
Git Branch Isolation
=====================
Manages agent task branches for safe file manipulation.

Each task gets a dedicated branch (agent/task-<id>).
All file writes are auto-committed to this branch.
User reviews diff and decides to merge or discard.

Security design:
  - Agent never commits to main directly
  - Branch names are deterministic (agent/task-<id>)
  - All git commands go through ShellExec validation
  - Merge requires explicit user approval
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from src.tools.shell_exec import ShellExec, ShellResult


@dataclass
class BranchInfo:
    """Information about the current agent branch."""

    branch_name: str
    task_id: str
    base_branch: str = "main"
    commits: int = 0
    active: bool = True

    @property
    def is_agent_branch(self) -> bool:
        return self.branch_name.startswith("agent/task-")


class GitBranchManager:
    """
    Manages git branches for agent task isolation.

    Lifecycle:
      1. start_task() — create and checkout agent branch
      2. commit_change() — auto-commit after approved writes
      3. get_diff() — show changes vs base branch
      4. apply() — merge into base branch
      5. discard() — delete agent branch
    """

    def __init__(self, shell: ShellExec) -> None:
        self._shell = shell
        self._current_branch: Optional[BranchInfo] = None

    @property
    def current_branch(self) -> Optional[BranchInfo]:
        return self._current_branch

    @property
    def has_active_branch(self) -> bool:
        return (
            self._current_branch is not None
            and self._current_branch.active
        )

    def _run_git(self, command: str) -> ShellResult:
        """Execute a git command through the shell pipeline."""
        return self._shell.execute(command)

    def _get_current_branch_name(self) -> Optional[str]:
        """Get the current git branch name."""
        result = self._run_git("git branch --show-current")
        if result.success:
            return result.stdout.strip()
        return None

    def _is_git_repo(self) -> bool:
        """Check if the workspace is a git repository."""
        result = self._run_git("git rev-parse --git-dir")
        return result.success

    def verify_git_health(self) -> tuple[bool, str]:
        """
        Verify git is functional in the workspace.

        Checks:
          1. Git is installed
          2. Workspace is a git repo (or can be initialized)
          3. Git operations work correctly

        Returns:
            (healthy, message) tuple.
        """
        # Check git is available
        result = self._run_git("git --version")
        if not result.success:
            return False, "Git is not installed or not in PATH."

        # Check if workspace is a repo
        if not self._is_git_repo():
            return True, (
                "Workspace is not a git repo. "
                "Running in git-unaware mode — "
                "file writes go directly with approval only. "
                "Initialize with 'git init' for branch isolation."
            )

        # Check git status works
        result = self._run_git("git status")
        if not result.success:
            return False, (
                f"Git status failed: {result.error or result.stderr}. "
                f"Repository may be corrupted."
            )

        # Check for leftover agent branches from previous sessions
        orphans = self.list_agent_branches()
        if orphans:
            current = self._get_current_branch_name()
            if current and current.startswith("agent/task-"):
                return False, (
                    f"Currently on agent branch: {current}. "
                    f"Run 'git checkout main' before starting."
                )
            return True, (
                f"Found {len(orphans)} orphaned agent branch(es): "
                f"{', '.join(orphans)}. "
                f"Use /branches and /discard to clean up."
            )

        return True, "Git is healthy."

    @property
    def is_git_workspace(self) -> bool:
        """Check if workspace is a git repository."""
        return self._is_git_repo()

    def init_repo_if_needed(self) -> bool:
        """
        Check if workspace is a git repo.

        Does NOT auto-create repos — respects user's choice.

        Returns:
            True if repo exists, False if not.
        """
        return self._is_git_repo()

    def start_task(
        self, task_id: Optional[str] = None
    ) -> Optional[BranchInfo]:
        """
        Create and checkout a new agent branch for a task.

        Returns None if workspace is not a git repo
        (git-unaware mode — no branch isolation).

        Args:
            task_id: Optional task ID. Auto-generated if not provided.

        Returns:
            BranchInfo if successful, None if not a git repo or failed.
        """
        if not self.is_git_workspace:
            return None

        if task_id is None:
            task_id = uuid.uuid4().hex[:8]

        branch_name = f"agent/task-{task_id}"

        # Get current branch as base
        base = self._get_current_branch_name() or "main"

        # Don't nest agent branches
        if base.startswith("agent/task-"):
            base = "main"

        # Create and checkout new branch
        result = self._run_git(
            f"git checkout -b {branch_name}"
        )
        if not result.success:
            # Branch might already exist
            result = self._run_git(
                f"git checkout {branch_name}"
            )
            if not result.success:
                return None

        self._current_branch = BranchInfo(
            branch_name=branch_name,
            task_id=task_id,
            base_branch=base,
            commits=0,
            active=True,
        )

        return self._current_branch

    def commit_change(
        self, message: str, files: Optional[list[str]] = None
    ) -> bool:
        """
        Auto-commit changes after an approved file write.

        Args:
            message: Commit message describing the change.
            files: Specific files to commit. None = all changes.

        Returns:
            True if commit succeeded.
        """
        if not self.has_active_branch:
            return False

        if files:
            for f in files:
                self._run_git(f"git add {f}")
        else:
            self._run_git("git add -A")

        # Check if there's anything to commit
        status = self._run_git("git status --porcelain")
        if not status.stdout.strip():
            return True  # Nothing to commit, that's ok

        safe_message = message.replace('"', '\\"')
        result = self._run_git(
            f'git commit -m "{safe_message}"'
        )

        if result.success and self._current_branch:
            self._current_branch.commits += 1

        return result.success

    def get_diff(self) -> str:
        """
        Get diff between agent branch and base branch.

        Returns:
            Diff output as string, or error message.
        """
        if not self.has_active_branch:
            return "No active agent branch."

        base = self._current_branch.base_branch
        branch = self._current_branch.branch_name

        result = self._run_git(
            f"git diff {base}..{branch}"
        )

        if result.success:
            return result.stdout or "(no changes)"
        return f"Error getting diff: {result.error or result.stderr}"

    def get_diff_summary(self) -> str:
        """
        Get a short summary of changes (files changed, insertions, deletions).

        Returns:
            Summary string.
        """
        if not self.has_active_branch:
            return "No active agent branch."

        base = self._current_branch.base_branch
        branch = self._current_branch.branch_name

        result = self._run_git(
            f"git diff --stat {base}..{branch}"
        )

        if result.success:
            return result.stdout or "(no changes)"
        return f"Error getting diff summary: {result.error}"

    def apply(self) -> tuple[bool, str]:
        """
        Merge agent branch into base branch.

        Returns:
            (success, message) tuple.
        """
        if not self.has_active_branch:
            return False, "No active agent branch to apply."

        base = self._current_branch.base_branch
        branch = self._current_branch.branch_name
        commits = self._current_branch.commits

        # Switch to base branch
        result = self._run_git(f"git checkout {base}")
        if not result.success:
            return False, (
                f"Failed to checkout {base}: "
                f"{result.error or result.stderr}"
            )

        # Merge agent branch
        result = self._run_git(
            f"git merge {branch} "
            f'--no-ff -m "Merge {branch}: '
            f'{commits} change(s) applied"'
        )
        if not result.success:
            # Rollback
            self._run_git(f"git checkout {branch}")
            return False, (
                f"Merge failed: {result.error or result.stderr}\n"
                f"Agent branch preserved. Resolve conflicts manually."
            )

        # Delete agent branch
        self._run_git(f"git branch -d {branch}")

        self._current_branch.active = False
        self._current_branch = None

        return True, (
            f"Merged {branch} into {base} "
            f"({commits} commit(s))."
        )

    def discard(self) -> tuple[bool, str]:
        """
        Discard agent branch and switch back to base.

        Returns:
            (success, message) tuple.
        """
        if not self.has_active_branch:
            return False, "No active agent branch to discard."

        base = self._current_branch.base_branch
        branch = self._current_branch.branch_name

        # Switch to base branch
        result = self._run_git(f"git checkout {base}")
        if not result.success:
            return False, (
                f"Failed to checkout {base}: "
                f"{result.error or result.stderr}"
            )

        # Force delete agent branch
        result = self._run_git(f"git branch -D {branch}")
        if not result.success:
            return False, (
                f"Failed to delete {branch}: "
                f"{result.error or result.stderr}"
            )

        self._current_branch.active = False
        self._current_branch = None

        return True, f"Discarded {branch}. Back on {base}."

    def list_agent_branches(self) -> list[str]:
        """List all agent branches in the repo."""
        result = self._run_git("git branch --list agent/task-*")
        if result.success and result.stdout.strip():
            return [
                b.strip().lstrip("* ")
                for b in result.stdout.strip().split("\n")
                if b.strip()
            ]
        return []
