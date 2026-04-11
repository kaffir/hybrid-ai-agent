"""
Input/Output Sanitizer
=======================
Defends against prompt injection in user inputs and
prevents sensitive data leakage in model outputs.

Security design:
  - Input sanitization: detects prompt injection patterns
  - Output sanitization: strips leaked credentials/keys
  - Path sanitization: normalizes paths for safe use
  - No blocking — flags suspicious content for awareness

OWASP LLM Top 10 coverage:
  - LLM01: Prompt Injection — detected and flagged
  - LLM02: Insecure Output Handling — outputs scanned
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SanitizationResult:
    """Result of sanitization check."""

    is_clean: bool
    original: str
    sanitized: str
    warnings: list[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


# Patterns that may indicate prompt injection attempts
_INJECTION_PATTERNS = [
    # Direct instruction override
    (
        r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
        "Prompt injection: instruction override attempt",
    ),
    (
        r"disregard\s+(all\s+)?(previous|above|prior)",
        "Prompt injection: disregard instruction attempt",
    ),
    (
        r"forget\s+(all\s+)?(previous|your)\s+(instructions|rules|guidelines)",
        "Prompt injection: forget instruction attempt",
    ),
    # Role hijacking
    (
        r"you\s+are\s+now\s+(a|an|the)",
        "Prompt injection: role reassignment attempt",
    ),
    (
        r"act\s+as\s+(a|an|the|if)",
        "Prompt injection: role hijacking attempt",
    ),
    (
        r"pretend\s+(to\s+be|you\s+are)",
        "Prompt injection: role pretend attempt",
    ),
    # System prompt extraction
    (
        r"(show|reveal|display|print|output)\s+(your|the)\s+system\s+prompt",
        "Prompt injection: system prompt extraction attempt",
    ),
    (
        r"what\s+(is|are)\s+your\s+(system|initial)\s+(prompt|instructions)",
        "Prompt injection: system prompt query attempt",
    ),
    # Delimiter injection
    (
        r"<\s*/?\s*system\s*>",
        "Prompt injection: system tag injection",
    ),
    (
        r"\[INST\]|\[/INST\]",
        "Prompt injection: instruction delimiter injection",
    ),
    # Encoded payloads
    (
        r"base64[:\s]+[A-Za-z0-9+/=]{20,}",
        "Suspicious: base64 encoded payload in input",
    ),
]

# Patterns for sensitive data that should not appear in outputs
_SENSITIVE_OUTPUT_PATTERNS = [
    # API keys
    (
        r"sk-ant-[a-zA-Z0-9\-_]{10,}",
        "Anthropic API key detected in output",
    ),
    (
        r"sk-[a-zA-Z0-9]{10,}",
        "OpenAI-style API key detected in output",
    ),
    # AWS credentials
    (
        r"AKIA[0-9A-Z]{16}",
        "AWS access key detected in output",
    ),
    (
        r"aws_secret_access_key\s*=\s*\S+",
        "AWS secret key detected in output",
    ),
    # Private keys
    (
        r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        "Private key detected in output",
    ),
    # Database connection strings
    (
        r"(mysql|postgres|postgresql|mongodb)://\S+:\S+@",
        "Database connection string with credentials detected",
    ),
    # Generic password patterns
    (
        r"password\s*[=:]\s*['\"][^'\"]{8,}['\"]",
        "Hardcoded password detected in output",
    ),
    # JWT tokens
    (
        r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.",
        "JWT token detected in output",
    ),
]


class Sanitizer:
    """
    Input/output sanitizer for the agent pipeline.

    Input: Scans user requests for prompt injection patterns.
    Output: Scans model responses for sensitive data leakage.

    Does NOT block — flags and warns so the user can decide.
    """

    def check_input(self, user_input: str) -> SanitizationResult:
        """
        Scan user input for prompt injection patterns.

        Does not modify the input — only flags concerns.

        Args:
            user_input: Raw user input string.

        Returns:
            SanitizationResult with warnings if suspicious.
        """
        warnings: list[str] = []

        input_lower = user_input.lower()

        for pattern, description in _INJECTION_PATTERNS:
            if re.search(pattern, input_lower, re.IGNORECASE):
                warnings.append(description)

        return SanitizationResult(
            is_clean=len(warnings) == 0,
            original=user_input,
            sanitized=user_input,  # Input is not modified
            warnings=warnings,
        )

    def check_output(self, model_output: str) -> SanitizationResult:
        """
        Scan model output for sensitive data leakage.

        Redacts detected sensitive data with [REDACTED] placeholders.

        Args:
            model_output: Raw model response string.

        Returns:
            SanitizationResult with sanitized output and warnings.
        """
        warnings: list[str] = []
        sanitized = model_output

        for pattern, description in _SENSITIVE_OUTPUT_PATTERNS:
            matches = re.findall(pattern, sanitized, re.IGNORECASE)
            if matches:
                warnings.append(
                    f"{description} ({len(matches)} occurrence(s))"
                )
                sanitized = re.sub(
                    pattern,
                    "[REDACTED]",
                    sanitized,
                    flags=re.IGNORECASE,
                )

        return SanitizationResult(
            is_clean=len(warnings) == 0,
            original=model_output,
            sanitized=sanitized,
            warnings=warnings,
        )

    def sanitize_path(self, path: str) -> str:
        """
        Normalize a file path for safe use.

        Removes null bytes, normalizes separators,
        and strips leading/trailing whitespace.

        Args:
            path: Raw path string.

        Returns:
            Normalized path string.
        """
        # Remove null bytes (path traversal technique)
        sanitized = path.replace("\x00", "")

        # Normalize path separators
        sanitized = sanitized.replace("\\", "/")

        # Strip whitespace
        sanitized = sanitized.strip()

        # Remove any control characters
        sanitized = re.sub(r"[\x01-\x1f\x7f]", "", sanitized)

        return sanitized
