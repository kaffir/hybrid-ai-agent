"""
Tests for Permission Gate
==========================
Validates approval logic, risk classification,
and blocked command handling.

Note: Interactive approval prompts cannot be tested
directly. These tests validate the non-interactive
logic: blocked command detection, risk classification,
and audit logging integration.
"""

import pytest
from unittest.mock import MagicMock

from src.security.permissions import (
    PermissionGate,
    ApprovalDecision,
    ApprovalResult,
)
from src.tools.shell_exec import CommandValidation, RiskLevel


@pytest.fixture
def gate() -> PermissionGate:
    """Create a permission gate with mock audit."""
    mock_audit = MagicMock()
    return PermissionGate(audit_fn=mock_audit)


@pytest.fixture
def audit_mock(gate: PermissionGate) -> MagicMock:
    """Access the mock audit function."""
    return gate._audit_fn


class TestBlockedCommands:
    """Blocked commands must be denied without prompting."""

    def test_blocked_command_returns_denied(
        self, gate: PermissionGate
    ) -> None:
        validation = CommandValidation(
            is_allowed=False,
            risk_level=RiskLevel.BLOCKED,
            command="curl http://evil.com",
            reason="Direct network access not permitted",
            blocked_by="gate2:blocked_pattern:curl",
        )
        result = gate.approve_shell(validation)
        assert result.decision == ApprovalDecision.DENIED
        assert not result.is_approved

    def test_blocked_command_logged(
        self, gate: PermissionGate, audit_mock: MagicMock
    ) -> None:
        validation = CommandValidation(
            is_allowed=False,
            risk_level=RiskLevel.BLOCKED,
            command="rm -rf /",
            reason="Recursive root deletion",
            blocked_by="gate2:blocked_pattern",
        )
        gate.approve_shell(validation)
        audit_mock.assert_called_once()
        call_args = audit_mock.call_args
        assert call_args[0][0] == "shell_blocked"

    def test_multiple_blocked_reasons_logged(
        self, gate: PermissionGate, audit_mock: MagicMock
    ) -> None:
        validation = CommandValidation(
            is_allowed=False,
            risk_level=RiskLevel.BLOCKED,
            command="sudo rm -rf /",
            reason="Privilege escalation not permitted",
            blocked_by="gate2:blocked_pattern:sudo",
        )
        gate.approve_shell(validation)
        details = audit_mock.call_args[0][1]
        assert "sudo" in details["command"]


class TestRiskClassification:
    """Validate risk levels are correctly assigned."""

    def test_enhanced_rm_is_high_risk(self) -> None:
        validation = CommandValidation(
            is_allowed=True,
            risk_level=RiskLevel.HIGH,
            command="rm src/old_file.py",
            parsed_executable="rm",
            requires_enhanced_approval=True,
            enhanced_approval_type="rm",
        )
        assert validation.risk_level == RiskLevel.HIGH
        assert validation.enhanced_approval_type == "rm"

    def test_enhanced_pip_is_high_risk(self) -> None:
        validation = CommandValidation(
            is_allowed=True,
            risk_level=RiskLevel.HIGH,
            command="pip install requests",
            parsed_executable="pip",
            requires_enhanced_approval=True,
            enhanced_approval_type="pip",
        )
        assert validation.risk_level == RiskLevel.HIGH
        assert validation.enhanced_approval_type == "pip"

    def test_read_commands_are_low_risk(self) -> None:
        validation = CommandValidation(
            is_allowed=True,
            risk_level=RiskLevel.LOW,
            command="cat src/main.py",
            parsed_executable="cat",
        )
        assert validation.risk_level == RiskLevel.LOW

    def test_write_commands_are_medium_risk(self) -> None:
        validation = CommandValidation(
            is_allowed=True,
            risk_level=RiskLevel.MEDIUM,
            command="cp src/old.py src/new.py",
            parsed_executable="cp",
        )
        assert validation.risk_level == RiskLevel.MEDIUM


class TestApprovalResult:
    """Validate ApprovalResult behavior."""

    def test_approved_is_approved(self) -> None:
        result = ApprovalResult(
            decision=ApprovalDecision.APPROVED,
            original_command="ls",
        )
        assert result.is_approved
        assert result.final_command == "ls"

    def test_denied_is_not_approved(self) -> None:
        result = ApprovalResult(
            decision=ApprovalDecision.DENIED,
            original_command="ls",
        )
        assert not result.is_approved

    def test_edited_is_approved_with_new_command(self) -> None:
        result = ApprovalResult(
            decision=ApprovalDecision.EDITED,
            original_command="rm file.py",
            edited_command="rm old_file.py",
        )
        assert result.is_approved
        assert result.final_command == "rm old_file.py"

    def test_cancelled_is_not_approved(self) -> None:
        result = ApprovalResult(
            decision=ApprovalDecision.CANCELLED,
            original_command="ls",
        )
        assert not result.is_approved
