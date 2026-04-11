"""
Audit Logger
=============
Records all agent actions, approval decisions, and
security events to a persistent log file.

Security design:
  - Append-only log file inside workspace
  - JSON-lines format for machine readability
  - Timestamps in UTC
  - Sensitive values redacted before logging
  - Log rotation not implemented (MVP) — noted as backlog

Storage: /workspace/.agent/audit.log
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class AuditLogger:
    """
    Append-only audit logger for agent actions.

    Every entry includes:
      - UTC timestamp
      - Event type (action category)
      - Details (event-specific data)
      - Agent mode at time of event
    """

    def __init__(
        self,
        workspace_root: str = "/workspace",
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._log_dir = Path(workspace_root) / ".agent"
        self._log_file = self._log_dir / "audit.log"

        if self._enabled:
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event_type: str,
        details: Optional[dict[str, Any]] = None,
        agent_mode: str = "",
    ) -> None:
        """
        Write an audit log entry.

        Args:
            event_type: Category of event (e.g., "shell_approved",
                        "file_write", "security_blocked").
            details: Event-specific key-value pairs.
            agent_mode: Current agent mode (HYBRID/LOCAL_ONLY).
        """
        if not self._enabled:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "mode": agent_mode,
            "details": self._redact_sensitive(details or {}),
        }

        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except (PermissionError, OSError):
            # Silently fail — audit logging should never break the agent
            pass

    def log_request(
        self,
        user_request: str,
        tier: str,
        model: str,
        agent_mode: str = "",
    ) -> None:
        """Log a user request and its routing decision."""
        self.log(
            "user_request",
            {
                "request": self._truncate(user_request, 200),
                "tier": tier,
                "model": model,
            },
            agent_mode=agent_mode,
        )

    def log_approval(
        self,
        action: str,
        command: str,
        decision: str,
        risk_level: str = "",
        agent_mode: str = "",
    ) -> None:
        """Log an approval decision."""
        self.log(
            "approval",
            {
                "action": action,
                "command": self._truncate(command, 200),
                "decision": decision,
                "risk_level": risk_level,
            },
            agent_mode=agent_mode,
        )

    def log_tool_execution(
        self,
        tool: str,
        command: str,
        success: bool,
        duration_ms: float = 0,
        agent_mode: str = "",
    ) -> None:
        """Log a tool execution result."""
        self.log(
            "tool_execution",
            {
                "tool": tool,
                "command": self._truncate(command, 200),
                "success": success,
                "duration_ms": round(duration_ms, 2),
            },
            agent_mode=agent_mode,
        )

    def log_security_event(
        self,
        event: str,
        details: dict,
        agent_mode: str = "",
    ) -> None:
        """Log a security-related event."""
        self.log(
            f"security:{event}",
            details,
            agent_mode=agent_mode,
        )

    def log_mode_change(
        self, old_mode: str, new_mode: str
    ) -> None:
        """Log an agent mode change."""
        self.log(
            "mode_change",
            {"old_mode": old_mode, "new_mode": new_mode},
            agent_mode=new_mode,
        )

    def get_recent(self, count: int = 20) -> list[dict]:
        """
        Read the most recent audit log entries.

        Args:
            count: Number of recent entries to return.

        Returns:
            List of log entry dicts, newest first.
        """
        if not self._log_file.exists():
            return []

        entries = []
        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except (PermissionError, OSError):
            return []

        return entries[-count:][::-1]  # Return newest first

    def _redact_sensitive(self, details: dict) -> dict:
        """
        Redact sensitive values from log entries.

        Replaces API keys, passwords, tokens with [REDACTED].
        """
        redacted = {}
        sensitive_keys = {
            "api_key", "password", "secret", "token",
            "credential", "key", "auth",
        }

        for k, v in details.items():
            key_lower = k.lower()
            if any(s in key_lower for s in sensitive_keys):
                redacted[k] = "[REDACTED]"
            elif isinstance(v, str) and len(v) > 0:
                # Check for API key patterns in values
                if v.startswith("sk-") or v.startswith("AKIA"):
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = v
            elif isinstance(v, dict):
                redacted[k] = self._redact_sensitive(v)
            else:
                redacted[k] = v

        return redacted

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate long strings for log entries."""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."
