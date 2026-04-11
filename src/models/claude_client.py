"""
Claude API Client
=================
Communicates with Anthropic's Messages API for complex
and security-sensitive tasks.

Security design:
  - API key from environment variable only
  - Hardcoded API endpoint (api.anthropic.com)
  - Explicit timeouts
  - No user-controlled URL construction
"""

from __future__ import annotations

import os
import httpx
from dataclasses import dataclass
from typing import Optional


_CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class ClaudeResponse:
    """Structured response from Claude API."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: Optional[str] = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ClaudeClient:
    """
    Client for Anthropic's Messages API.

    API key is read from ANTHROPIC_API_KEY environment variable.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        default_timeout: float = 180.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._default_timeout = default_timeout

        if not self._api_key:
            self._available = False
        else:
            self._available = True

        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=10.0,
                read=self._default_timeout,
                write=10.0,
                pool=10.0,
            ),
        )

    def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout_seconds: Optional[float] = None,
    ) -> ClaudeResponse:
        """
        Send a chat request to Claude API.

        Args:
            messages: List of message dicts with "role" and "content".
            system_prompt: Optional system prompt.
            model: Override the default model.
            temperature: Sampling temperature.
            max_tokens: Maximum response tokens.
            timeout_seconds: Per-request timeout override.

        Returns:
            ClaudeResponse with content and usage metrics.

        Raises:
            ClaudeAPIError: If the API returns an error.
            ClaudeConnectionError: If the API is unreachable.
            ClaudeAuthError: If the API key is invalid or missing.
            ClaudeTimeoutError: If the request exceeds timeout.
        """
        if not self._available:
            raise ClaudeAuthError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it in your .env file or switch to LOCAL_ONLY mode."
            )

        target_model = model or self._model
        request_timeout = timeout_seconds or self._default_timeout

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        }

        payload: dict = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = self._client.post(
                _CLAUDE_API_URL,
                headers=headers,
                json=payload,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=request_timeout,
                    write=10.0,
                    pool=10.0,
                ),
            )
        except httpx.ConnectError as e:
            raise ClaudeConnectionError(
                f"Cannot connect to Claude API. "
                f"Check your internet connection. Error: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise ClaudeTimeoutError(
                f"Claude API request timed out after {request_timeout}s. "
                f"Consider breaking the task into smaller pieces. "
                f"Error: {e}"
            ) from e

        if response.status_code == 401:
            raise ClaudeAuthError("Invalid ANTHROPIC_API_KEY.")
        elif response.status_code == 429:
            raise ClaudeRateLimitError("Claude API rate limit exceeded.")
        elif response.status_code >= 500:
            raise ClaudeAPIError(
                f"Claude API server error (HTTP {response.status_code}): "
                f"{response.text}"
            )
        elif response.status_code != 200:
            raise ClaudeAPIError(
                f"Claude API error (HTTP {response.status_code}): "
                f"{response.text}"
            )

        data = response.json()

        content_blocks = data.get("content", [])
        text_parts = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        usage = data.get("usage", {})

        return ClaudeResponse(
            content="\n".join(text_parts),
            model=data.get("model", target_model),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=data.get("stop_reason"),
        )

    def is_available(self) -> bool:
        """Check if Claude API is reachable and authenticated."""
        if not self._available:
            return False
        try:
            self.chat(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True
        except (ClaudeConnectionError, ClaudeAuthError, ClaudeRateLimitError):
            return False
        except ClaudeAPIError:
            return True

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class ClaudeConnectionError(Exception):
    """Raised when Claude API is unreachable."""
    pass


class ClaudeAuthError(Exception):
    """Raised when API key is invalid or missing."""
    pass


class ClaudeRateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class ClaudeTimeoutError(Exception):
    """Raised when request exceeds timeout."""
    pass


class ClaudeAPIError(Exception):
    """Raised for general API errors."""
    pass
