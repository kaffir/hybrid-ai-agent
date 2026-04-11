"""
Mode-Aware Model Resolver
=========================
Maps (tier, mode) → target model + behavioral flags.

Modes:
  HYBRID     — full capability (local + cloud)
  LOCAL_ONLY — all tasks handled locally, security tasks get disclaimers
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.router.rule_router import Tier


class AgentMode(str, Enum):
    """Agent operation mode."""

    HYBRID = "HYBRID"
    LOCAL_ONLY = "LOCAL_ONLY"


@dataclass
class ModelAssignment:
    """Result of model resolution."""

    model: str
    is_local: bool
    requires_disclaimer: bool = False
    disclaimer_type: Optional[str] = None
    offer_pending_queue: bool = False

    @property
    def provider(self) -> str:
        """Return 'ollama' or 'claude' based on model assignment."""
        if self.is_local:
            return "ollama"
        return "claude"


class ModelResolver:
    """
    Resolves (tier, mode) to a concrete model assignment.

    This is the single point where operation mode affects
    model selection. The router is mode-unaware by design.
    """

    def __init__(
        self,
        primary_model: str = "gemma4:26b",
        fallback_model: str = "gemma4:e4b",
        cloud_model: str = "claude-sonnet-4-20250514",
        mode: AgentMode = AgentMode.HYBRID,
    ) -> None:
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.cloud_model = cloud_model
        self.mode = mode

    def set_mode(self, mode: AgentMode) -> None:
        """Switch operation mode at runtime."""
        self.mode = mode

    def resolve(
        self, tier: Tier, is_security_task: bool = False
    ) -> ModelAssignment:
        """
        Resolve a tier to a model assignment based on current mode.

        Args:
            tier: The classified task tier from the router.
            is_security_task: Whether the router flagged this as security.

        Returns:
            ModelAssignment with model, provider, and disclaimer flags.
        """
        if self.mode == AgentMode.HYBRID:
            return self._resolve_hybrid(tier)
        elif self.mode == AgentMode.LOCAL_ONLY:
            return self._resolve_local_only(tier, is_security_task)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def _resolve_hybrid(self, tier: Tier) -> ModelAssignment:
        """HYBRID: local for SIMPLE/MEDIUM, cloud for COMPLEX."""
        if tier == Tier.SIMPLE:
            return ModelAssignment(
                model=self.fallback_model,
                is_local=True,
            )
        elif tier == Tier.MEDIUM:
            return ModelAssignment(
                model=self.primary_model,
                is_local=True,
            )
        else:  # COMPLEX
            return ModelAssignment(
                model=self.cloud_model,
                is_local=False,
            )

    def _resolve_local_only(
        self, tier: Tier, is_security_task: bool
    ) -> ModelAssignment:
        """LOCAL_ONLY: everything local, security tasks get disclaimers."""
        if tier == Tier.SIMPLE:
            return ModelAssignment(
                model=self.fallback_model,
                is_local=True,
            )

        # MEDIUM and COMPLEX both go to primary local model
        if is_security_task:
            return ModelAssignment(
                model=self.primary_model,
                is_local=True,
                requires_disclaimer=True,
                disclaimer_type="security",
                offer_pending_queue=True,
            )

        return ModelAssignment(
            model=self.primary_model,
            is_local=True,
        )
