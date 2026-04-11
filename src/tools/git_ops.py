"""
Git Operations
==============
Wrapper around common git commands.

All commands execute through the ShellExec pipeline,
inheriting its security validation and approval flow.

Security design:
  - No direct subprocess calls — uses ShellExec
  - Git commands operate within workspace only
  - Push/pull operations classified as MEDIUM risk
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.tools.shell_exec import ShellExec, ShellResult, CommandValidation


@dataclass
class GitStatus:
    """Parsed git status information."""

    branch: str = ""
    clean: bool = True
    modified: list[str] = None
    untracked: list[str] = None
    staged: list[str] = None

    def __post_init__(self):
        self.modified = self.modified or []
        self.untracked = self.untracked or []
        self.staged = self.staged or []

    @property
    def summary(self) -> str:
        parts = [f"Branch: {self.branch}"]
        if self.clean:
            parts.append("Working tree clean")
        else:
            if self.staged:
                parts.append(f"Staged: {len(self.staged)} file(s)")
            if self.modified:
                parts.append(f"Modified: {len(self.modified)} file(s)")
            if self.untracked:
                parts.append(f"Untracked: {len(self.untracked)} file(s)")
        return " | ".join(parts)


class GitOps:
    """
    Git operations executed through the sandboxed shell.

    Each method returns:
      - A CommandValidation (for commands needing approval)
      - Or a ShellResult (for read-only commands after validation)
    """

    def __init__(self, shell: ShellExec) -> None:
        self._shell = shell

    def validate_command(self, git_command: str) -> CommandValidation:
        """
        Validate a git command through the security pipeline.

        Args:
            git_command: Full git command (e.g., "git status").

        Returns:
            CommandValidation result.
        """
        return self._shell.validate(git_command)

    def execute_command(
        self, git_command: str, timeout: Optional[float] = None
    ) -> ShellResult:
        """
        Execute a validated git command.

        Only call after validation and approval.
        """
        return self._shell.execute(git_command, timeout=timeout)

    def status(self) -> ShellResult:
        """
        Run git status (read-only, low risk).

        Returns raw ShellResult — caller should validate first.
        """
        return self._shell.execute("git status --porcelain --branch")

    def parse_status(self, raw_output: str) -> GitStatus:
        """Parse git status --porcelain output into GitStatus."""
        status = GitStatus()
        lines = raw_output.strip().split("\n")

        for line in lines:
            if line.startswith("## "):
                # Branch info
                branch_part = line[3:].split("...")[0]
                status.branch = branch_part
            elif line.startswith("M ") or line.startswith(" M"):
                status.modified.append(line[3:].strip())
                status.clean = False
            elif line.startswith("A "):
                status.staged.append(line[3:].strip())
                status.clean = False
            elif line.startswith("?? "):
                status.untracked.append(line[3:].strip())
                status.clean = False
            elif line.strip():
                status.clean = False

        return status

    def diff(self, path: Optional[str] = None) -> str:
        """Build a git diff command."""
        if path:
            return f"git diff -- {path}"
        return "git diff"

    def log(self, count: int = 10) -> str:
        """Build a git log command."""
        return f"git log --oneline -n {count}"

    def add(self, path: str = ".") -> str:
        """Build a git add command."""
        return f"git add {path}"

    def commit(self, message: str) -> str:
        """Build a git commit command."""
        safe_message = message.replace('"', '\\"')
        return f'git commit -m "{safe_message}"'

    def checkout(self, target: str) -> str:
        """Build a git checkout command."""
        return f"git checkout {target}"
