"""
Rule-Based Task Router
======================
Classifies user requests into SIMPLE, MEDIUM, or COMPLEX tiers
using keyword matching, scope signals, and security overrides.

Security design:
  - No LLM in the routing path (prevents prompt injection in routing)
  - Security keywords ALWAYS force COMPLEX tier
  - Default tier is MEDIUM (conservative fallback)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


class Tier(str, Enum):
    """Processing tier for task routing."""

    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"


@dataclass
class RoutingResult:
    """Result of routing classification."""

    tier: Tier
    confidence: float
    matched_rules: list[str] = field(default_factory=list)
    security_override: bool = False
    scope_elevation: Optional[str] = None

    def summary(self) -> str:
        """Human-readable summary of routing decision."""
        parts = [f"Tier: {self.tier.value} (confidence: {self.confidence:.0%})"]
        if self.security_override:
            parts.append("⚠️  SECURITY OVERRIDE — forced to COMPLEX")
        if self.scope_elevation:
            parts.append(f"Scope elevation: {self.scope_elevation}")
        if self.matched_rules:
            parts.append(f"Matched: {', '.join(self.matched_rules[:5])}")
        return " | ".join(parts)


class RuleRouter:
    """
    Rule-based router that classifies requests into processing tiers.

    Security invariant: security_override keywords ALWAYS produce
    Tier.COMPLEX, regardless of any other signals. This cannot be
    bypassed by prompt content.
    """

    def __init__(self, config_path: str | Path = "config/routing_rules.yml") -> None:
        self._config_path = Path(config_path)
        self._config = self._load_config()
        self._security_keywords: list[str] = self._config.get(
            "security_override", {}
        ).get("keywords", [])
        self._task_keywords: dict = self._config.get("task_keywords", {})
        self._scope_signals: dict = self._config.get("scope_signals", {})
        self._default_tier = Tier(
            self._config.get("default_tier", "MEDIUM")
        )
        self._confidence_threshold: float = self._config.get(
            "confidence_threshold", 0.6
        )

    def _load_config(self) -> dict:
        """Load routing rules from YAML configuration."""
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Routing config not found: {self._config_path}"
            )

        with open(self._config_path, "r") as f:
            config = yaml.safe_load(f)

        if not isinstance(config, dict):
            raise ValueError("Routing config must be a YAML dictionary")

        return config

    def reload_config(self) -> None:
        """
        Reload routing rules from disk.

        Allows runtime rule updates without restarting the agent.
        """
        self._config = self._load_config()
        self._security_keywords = self._config.get(
            "security_override", {}
        ).get("keywords", [])
        self._task_keywords = self._config.get("task_keywords", {})
        self._scope_signals = self._config.get("scope_signals", {})

    def classify(self, request: str) -> RoutingResult:
        """
        Classify a user request into a processing tier.

        Priority order:
          1. Security override (ALWAYS wins → COMPLEX)
          2. Scope signal elevation
          3. Keyword voting
          4. Default tier

        Args:
            request: The user's raw request text.

        Returns:
            RoutingResult with tier, confidence, and matched rules.
        """
        request_lower = request.lower().strip()
        matched_rules: list[str] = []

        # ── Priority 1: Security override ──
        security_match = self._check_security_override(request_lower)
        if security_match:
            return RoutingResult(
                tier=Tier.COMPLEX,
                confidence=1.0,
                matched_rules=[f"security:{m}" for m in security_match],
                security_override=True,
            )

        # ── Priority 2: Scope signal check (before keyword voting) ──
        scope_elevation = None
        scope_forced_tier: Optional[Tier] = None

        # Check for MEDIUM → COMPLEX elevation first (higher priority)
        for signal in self._scope_signals.get("elevate_to_complex", []):
            if signal["pattern"].lower() in request_lower:
                weight = signal.get("weight", 3.0)
                if weight >= 5.0:
                    # Strong scope signal — force COMPLEX regardless of keywords
                    scope_forced_tier = Tier.COMPLEX
                scope_elevation = signal["reason"]
                matched_rules.append(f"scope:{signal['pattern']}")
                break

        # Check for SIMPLE → MEDIUM elevation
        if not scope_elevation:
            for signal in self._scope_signals.get("elevate_to_medium", []):
                if signal["pattern"].lower() in request_lower:
                    scope_elevation = signal["reason"]
                    matched_rules.append(f"scope:{signal['pattern']}")
                    break

        # If scope signal forces a tier, return immediately
        if scope_forced_tier is not None:
            return RoutingResult(
                tier=scope_forced_tier,
                confidence=0.85,
                matched_rules=matched_rules,
                scope_elevation=scope_elevation,
            )

        # ── Priority 3: Keyword voting ──
        scores: dict[Tier, float] = {
            Tier.SIMPLE: 0.0,
            Tier.MEDIUM: 0.0,
            Tier.COMPLEX: 0.0,
        }

        for tier_name, keywords_config in self._task_keywords.items():
            tier = Tier(tier_name)

            # Check phrases first (longer matches = stronger signal)
            phrases = keywords_config.get("phrases", [])
            for phrase in phrases:
                if phrase.lower() in request_lower:
                    scores[tier] += 2.0  # Phrases worth more than single words
                    matched_rules.append(f"phrase:{phrase}")

            # Then single words
            single_words = keywords_config.get("single_words", [])
            for word in single_words:
                # Word boundary match to avoid partial matches
                pattern = rf"\b{re.escape(word.lower())}\b"
                if re.search(pattern, request_lower):
                    scores[tier] += 1.0
                    matched_rules.append(f"word:{word}")

        # Apply scope elevation as score boost (for non-forced cases)
        if scope_elevation:
            for signal in self._scope_signals.get("elevate_to_medium", []):
                if signal["pattern"].lower() in request_lower:
                    scores[Tier.MEDIUM] += 1.5
                    break

        # ── Determine winner ──
        total_score = sum(scores.values())

        if total_score == 0:
            # No keywords matched — use default
            return RoutingResult(
                tier=self._default_tier,
                confidence=0.3,
                matched_rules=matched_rules or ["default:no keywords matched"],
                scope_elevation=scope_elevation,
            )

        # Winner is the tier with the highest score
        winning_tier = max(scores, key=scores.get)  # type: ignore[arg-type]
        confidence = scores[winning_tier] / total_score

        return RoutingResult(
            tier=winning_tier,
            confidence=confidence,
            matched_rules=matched_rules,
            scope_elevation=scope_elevation,
        )

    def _check_security_override(self, request_lower: str) -> list[str]:
        """
        Check if request contains any security-related keywords.

        Returns list of matched security keywords, or empty list.

        Security invariant: this check CANNOT be disabled or bypassed.
        """
        matches = []
        for keyword in self._security_keywords:
            if keyword.lower() in request_lower:
                matches.append(keyword)
        return matches

    def get_model_for_tier(
        self,
        tier: Tier,
        primary_model: str = "gemma4:26b",
        fallback_model: str = "gemma4:e4b",
        cloud_model: str = "claude-sonnet-4-20250514",
    ) -> str:
        """
        Map a tier to its target model identifier.

        Args:
            tier: The classified tier.
            primary_model: Ollama model for MEDIUM tasks.
            fallback_model: Ollama model for SIMPLE tasks.
            cloud_model: Claude model for COMPLEX tasks.

        Returns:
            Model identifier string.
        """
        mapping = {
            Tier.SIMPLE: fallback_model,
            Tier.MEDIUM: primary_model,
            Tier.COMPLEX: cloud_model,
        }
        return mapping[tier]
