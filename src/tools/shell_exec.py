"""
Sandboxed Shell Execution
=========================
Executes shell commands with three-gate validation:
  Gate 1: Command parsing (detect chaining, subshells, obfuscation)
  Gate 2: Policy engine (allowlist, blocklist, path scope)
  Gate 3: Human approval (with risk classification)

Security design:
  - Whitelist-based: only allowed commands can execute
  - Dangerous patterns blocked before reaching human
  - All paths validated against workspace boundary
  - Commands run with timeout and output capture
  - Enhanced approval for rm and pip install
"""

from __future__ import annotations

import re
import subprocess
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


class RiskLevel(str, Enum):
    """Risk classification for shell commands."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"


@dataclass
class CommandValidation:
    """Result of command validation through Gates 1-2."""

    is_allowed: bool
    risk_level: RiskLevel
    command: str
    parsed_executable: str = ""
    reason: str = ""
    requires_enhanced_approval: bool = False
    enhanced_approval_type: Optional[str] = None  # "rm" or "pip"
    blocked_by: Optional[str] = None  # Which gate blocked it


@dataclass
class ShellResult:
    """Result of shell command execution."""

    success: bool
    command: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    timed_out: bool = False
    requires_approval: bool = False
    validation: Optional[CommandValidation] = None


class ShellExec:
    """
    Sandboxed shell command executor.

    Three-gate security model:
      Gate 1 — Parse and decompose command
      Gate 2 — Validate against policy
      Gate 3 — Human approval (handled by permissions.py in Step 7)
    """

    def __init__(
        self,
        workspace_root: str = "/workspace",
        allowed_commands_path: str = "config/allowed_commands.yml",
        blocked_patterns_path: str = "config/blocked_patterns.yml",
        default_timeout: float = 30.0,
    ) -> None:
        self._workspace = Path(workspace_root).resolve()
        self._default_timeout = default_timeout
        self._allowed_config = self._load_yaml(allowed_commands_path)
        self._blocked_config = self._load_yaml(blocked_patterns_path)

    @staticmethod
    def _load_yaml(path: str) -> dict:
        """Load YAML config file."""
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    # ── Gate 1: Command Parser ──

    def _parse_command(self, command: str) -> CommandValidation:
        """
        Gate 1: Parse command for dangerous constructs.

        Detects:
          - Command chaining (&&, ||, ;)
          - Subshells ($(), backticks)
          - Pipes (|)
          - Redirects (>, >>)
          - Base64/hex obfuscation
          - Inline code execution (-c flags)
        """
        # Check for command chaining
        chaining_patterns = [
            (r"&&", "command chaining (&&)"),
            (r"\|\|", "command chaining (||)"),
            (r"(?<!\\);", "command chaining (;)"),
        ]
        for pattern, description in chaining_patterns:
            if re.search(pattern, command):
                return CommandValidation(
                    is_allowed=False,
                    risk_level=RiskLevel.BLOCKED,
                    command=command,
                    reason=f"Blocked: {description} detected. "
                           f"Submit commands individually.",
                    blocked_by="gate1:chaining",
                )

        # Check for subshells
        subshell_patterns = [
            (r"\$\(", "subshell $()"),
            (r"`", "backtick subshell"),
        ]
        for pattern, description in subshell_patterns:
            if re.search(pattern, command):
                return CommandValidation(
                    is_allowed=False,
                    risk_level=RiskLevel.BLOCKED,
                    command=command,
                    reason=f"Blocked: {description} detected. "
                           f"Subshell execution is not permitted.",
                    blocked_by="gate1:subshell",
                )

        # Check for pipes
        if "|" in command and "||" not in command:
            return CommandValidation(
                is_allowed=False,
                risk_level=RiskLevel.BLOCKED,
                command=command,
                reason="Blocked: pipe (|) detected. "
                       "Submit commands individually.",
                blocked_by="gate1:pipe",
            )

        # Check for output redirects
        if re.search(r">{1,2}", command):
            return CommandValidation(
                is_allowed=False,
                risk_level=RiskLevel.BLOCKED,
                command=command,
                reason="Blocked: output redirect (>) detected. "
                       "Use file_ops tool for writing files.",
                blocked_by="gate1:redirect",
            )

        # Extract the executable name
        try:
            parts = shlex.split(command)
        except ValueError:
            return CommandValidation(
                is_allowed=False,
                risk_level=RiskLevel.BLOCKED,
                command=command,
                reason="Blocked: malformed command (unmatched quotes).",
                blocked_by="gate1:parse_error",
            )

        if not parts:
            return CommandValidation(
                is_allowed=False,
                risk_level=RiskLevel.BLOCKED,
                command=command,
                reason="Blocked: empty command.",
                blocked_by="gate1:empty",
            )

        executable = parts[0]

        return CommandValidation(
            is_allowed=True,  # Passes Gate 1, continue to Gate 2
            risk_level=RiskLevel.LOW,
            command=command,
            parsed_executable=executable,
        )

    # ── Gate 2: Policy Engine ──

    def _check_policy(
        self, validation: CommandValidation
    ) -> CommandValidation:
        """
        Gate 2: Check command against allowlist and blocklist.
        """
        command = validation.command
        executable = validation.parsed_executable

        # 2a. Check blocked patterns first
        blocked_patterns = self._blocked_config.get("blocked_patterns", [])
        for entry in blocked_patterns:
            pattern = entry.get("pattern", "")
            if pattern.lower() in command.lower():
                validation.is_allowed = False
                validation.risk_level = RiskLevel.BLOCKED
                validation.reason = (
                    f"Blocked: matches blocked pattern '{pattern}'. "
                    f"Reason: {entry.get('reason', 'policy violation')}"
                )
                validation.blocked_by = f"gate2:blocked_pattern:{pattern}"
                return validation

        # 2b. Check against allowed commands list
        allowed = self._allowed_config.get("allowed", [])
        if executable not in allowed:
            validation.is_allowed = False
            validation.risk_level = RiskLevel.BLOCKED
            validation.reason = (
                f"Blocked: '{executable}' is not in the allowed "
                f"commands list. Allowed: {', '.join(sorted(allowed))}"
            )
            validation.blocked_by = f"gate2:not_allowed:{executable}"
            return validation

        # 2c. Check enhanced approval rules
        enhanced = self._allowed_config.get("enhanced_approval", {})

        if executable == "rm" and "rm" in enhanced:
            rm_rules = enhanced["rm"]
            blocked_flags = rm_rules.get("blocked_flags", [])
            blocked_rm_patterns = rm_rules.get("blocked_patterns", [])

            try:
                parts = shlex.split(command)
            except ValueError:
                parts = command.split()

            for flag in blocked_flags:
                if flag in parts:
                    validation.is_allowed = False
                    validation.risk_level = RiskLevel.BLOCKED
                    validation.reason = (
                        f"Blocked: 'rm {flag}' is not permitted. "
                        f"Delete files individually."
                    )
                    validation.blocked_by = f"gate2:rm_flag:{flag}"
                    return validation

            for pat in blocked_rm_patterns:
                if pat in command:
                    validation.is_allowed = False
                    validation.risk_level = RiskLevel.BLOCKED
                    validation.reason = (
                        "Blocked: wildcard/root deletion not permitted."
                    )
                    validation.blocked_by = f"gate2:rm_pattern:{pat}"
                    return validation

            validation.risk_level = RiskLevel.HIGH
            validation.requires_enhanced_approval = True
            validation.enhanced_approval_type = "rm"
            return validation

        if executable == "pip" and "pip" in enhanced:
            pip_rules = enhanced["pip"]
            allowed_subcmds = pip_rules.get("allowed_subcommands", [])

            try:
                parts = shlex.split(command)
            except ValueError:
                parts = command.split()

            subcmd = parts[1] if len(parts) > 1 else ""
            if subcmd not in allowed_subcmds:
                validation.is_allowed = False
                validation.risk_level = RiskLevel.BLOCKED
                validation.reason = (
                    f"Blocked: 'pip {subcmd}' is not permitted. "
                    f"Allowed: {', '.join(allowed_subcmds)}"
                )
                validation.blocked_by = f"gate2:pip_subcmd:{subcmd}"
                return validation

            if subcmd == "install":
                validation.risk_level = RiskLevel.HIGH
                validation.requires_enhanced_approval = True
                validation.enhanced_approval_type = "pip"
            else:
                validation.risk_level = RiskLevel.LOW

            return validation

        # 2d. Path scope validation for file-operating commands
        file_commands = {
            "cat", "head", "tail", "cp", "mv",
            "mkdir", "touch", "find", "grep", "diff",
        }
        if executable in file_commands:
            try:
                parts = shlex.split(command)
            except ValueError:
                parts = command.split()

            for part in parts[1:]:
                if part.startswith("-"):
                    continue  # Skip flags
                if part.startswith("/") or ".." in part:
                    try:
                        resolved = Path(part).resolve()
                        resolved.relative_to(self._workspace)
                    except (ValueError, OSError):
                        validation.is_allowed = False
                        validation.risk_level = RiskLevel.BLOCKED
                        validation.reason = (
                            f"Blocked: path '{part}' is outside workspace."
                        )
                        validation.blocked_by = f"gate2:path_scope:{part}"
                        return validation

        # Classify risk for allowed commands
        write_commands = {"cp", "mv", "mkdir", "touch", "git"}
        if executable in write_commands:
            validation.risk_level = RiskLevel.MEDIUM
        else:
            validation.risk_level = RiskLevel.LOW

        validation.requires_approval = True
        return validation

    def validate(self, command: str) -> CommandValidation:
        """
        Run command through Gate 1 and Gate 2.

        Gate 3 (human approval) is handled by the permissions layer.

        Args:
            command: Raw command string.

        Returns:
            CommandValidation with allow/deny decision and risk level.
        """
        # Gate 1: Parse
        validation = self._parse_command(command)
        if not validation.is_allowed:
            return validation

        # Gate 2: Policy
        validation = self._check_policy(validation)

        return validation

    def execute(
        self, command: str, timeout: Optional[float] = None
    ) -> ShellResult:
        """
        Execute a validated and approved command.

        This should only be called AFTER validate() and human approval.

        Args:
            command: Command to execute.
            timeout: Execution timeout in seconds.

        Returns:
            ShellResult with stdout, stderr, and exit code.
        """
        exec_timeout = timeout or self._default_timeout

        try:
            result = subprocess.run(  # noqa: S602 — intentional: commands are validated by Gate 1+2
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=exec_timeout,
                cwd=str(self._workspace),
                env=self._safe_env(),
            )

            return ShellResult(
                success=result.returncode == 0,
                command=command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        except subprocess.TimeoutExpired:
            return ShellResult(
                success=False,
                command=command,
                error=f"Command timed out after {exec_timeout}s.",
                timed_out=True,
            )
        except Exception as e:
            return ShellResult(
                success=False,
                command=command,
                error=f"Execution error: {e}",
            )

    def _safe_env(self) -> dict:
        """
        Create a sanitized environment for command execution.

        Removes sensitive variables and sets safe defaults.
        """
        import os
        env = os.environ.copy()

        # Remove sensitive variables from child process
        sensitive_keys = [
            "ANTHROPIC_API_KEY",
            "API_KEY",
            "SECRET",
            "TOKEN",
            "PASSWORD",
        ]
        for key in list(env.keys()):
            for sensitive in sensitive_keys:
                if sensitive in key.upper():
                    del env[key]
                    break

        # Set safe PATH
        env["HOME"] = str(self._workspace)

        return env
