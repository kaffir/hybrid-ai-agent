"""
Ollama API Client
=================
Communicates with Ollama's native /api/chat endpoint
for local model inference (Gemma 4 26B + E4B).

Security design:
  - Hardcoded allowed base URLs (localhost / host.docker.internal)
  - Explicit timeouts to prevent hanging
  - No user-controlled URL construction
  - Uses native /api/chat (not /v1) to avoid Gemma 4 streaming bugs
"""

from __future__ import annotations

import httpx
from dataclasses import dataclass
from typing import Optional


# Security: Only these base URLs are permitted
_ALLOWED_OLLAMA_HOSTS = (
    "http://localhost:11434",
    "http://127.0.0.1:11434",
    "http://host.docker.internal:11434",
)


@dataclass
class OllamaResponse:
    """Structured response from Ollama."""

    content: str
    model: str
    total_duration_ms: float
    eval_count: int  # tokens generated
    eval_duration_ms: float  # time spent generating

    @property
    def tokens_per_second(self) -> float:
        """Calculate generation speed."""
        if self.eval_duration_ms <= 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ms / 1000.0)


class OllamaClient:
    """
    Client for Ollama's native chat API.

    Uses /api/chat with think:false for Gemma 4 compatibility.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_timeout: float = 120.0,
    ) -> None:
        # Security: Validate base URL against allowlist
        if base_url.rstrip("/") not in _ALLOWED_OLLAMA_HOSTS:
            raise ValueError(
                f"Ollama base URL '{base_url}' is not in the allowed list. "
                f"Allowed: {_ALLOWED_OLLAMA_HOSTS}"
            )
        self._base_url = base_url.rstrip("/")
        self._default_timeout = default_timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=10.0,
                read=self._default_timeout,
                write=10.0,
                pool=10.0,
            ),
        )

    def chat(
        self,
        model: str,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        timeout_seconds: Optional[float] = None,
    ) -> OllamaResponse:
        """
        Send a chat request to Ollama.

        Args:
            model: Model name (e.g., "gemma4:26b").
            messages: List of message dicts with "role" and "content".
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            timeout_seconds: Per-request timeout override.

        Returns:
            OllamaResponse with content and performance metrics.

        Raises:
            OllamaConnectionError: If Ollama is unreachable.
            OllamaModelError: If the model fails to generate.
            OllamaTimeoutError: If the request exceeds timeout.
        """
        payload: dict = {
            "model": model,
            "messages": [],
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
            },
        }

        if system_prompt:
            payload["messages"].append({
                "role": "system",
                "content": system_prompt,
            })

        payload["messages"].extend(messages)

        # Use per-request timeout if provided
        request_timeout = timeout_seconds or self._default_timeout

        try:
            response = self._client.post(
                "/api/chat",
                json=payload,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=request_timeout,
                    write=10.0,
                    pool=10.0,
                ),
            )
            response.raise_for_status()
        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self._base_url}. "
                f"Is Ollama running? Error: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Request timed out after {request_timeout}s. "
                f"Consider breaking the task into smaller pieces. "
                f"Error: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise OllamaModelError(
                f"Ollama returned HTTP {e.response.status_code}: "
                f"{e.response.text}"
            ) from e

        data = response.json()

        return OllamaResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", model),
            total_duration_ms=data.get("total_duration", 0) / 1_000_000,
            eval_count=data.get("eval_count", 0),
            eval_duration_ms=data.get("eval_duration", 0) / 1_000_000,
        )

    def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            response = self._client.get("/api/version")
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def is_model_available(self, model: str) -> bool:
        """Check if a specific model is pulled and ready."""
        try:
            response = self._client.post(
                "/api/show", json={"name": model}
            )
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class OllamaConnectionError(Exception):
    """Raised when Ollama is unreachable."""
    pass


class OllamaModelError(Exception):
    """Raised when the model fails to generate a response."""
    pass


class OllamaTimeoutError(Exception):
    """Raised when request exceeds timeout."""
    pass
