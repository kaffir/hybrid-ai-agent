"""
Tests for Rule-Based Router
============================
Validates routing classification, security overrides,
scope elevation, and edge cases.
"""

import pytest
from src.router.rule_router import RuleRouter, Tier


@pytest.fixture
def router() -> RuleRouter:
    """Create router with default config."""
    return RuleRouter(config_path="config/routing_rules.yml")


# ── Security Override Tests ──
# These are the most critical tests: security keywords
# must ALWAYS route to COMPLEX regardless of other signals.


class TestSecurityOverride:
    """Security keywords must ALWAYS force COMPLEX tier."""

    @pytest.mark.parametrize(
        "user_input",
        [
            "Check for SQL injection in the login form",
            "Review the authentication flow",
            "Are there any XSS vulnerabilities?",
            "Implement JWT token validation",
            "Add CSRF protection to the API",
            "Review OWASP compliance",
            "Check for privilege escalation paths",
            "Implement rate limiting on the endpoints",
            "Add input validation to sanitize input from users",
            "Review the access control for admin endpoints",
        ],
    )
    def test_security_keywords_force_complex(
        self, router: RuleRouter, user_input: str
    ) -> None:
        result = router.classify(user_input)
        assert result.tier == Tier.COMPLEX, (
            f"Security request '{user_input}' was routed to {result.tier} "
            f"instead of COMPLEX. Matched: {result.matched_rules}"
        )
        assert result.security_override is True
        assert result.confidence == 1.0

    def test_security_override_beats_simple_keywords(
        self, router: RuleRouter
    ) -> None:
        """Even if request has SIMPLE keywords, security wins."""
        user_input = "Format the authentication module code"
        result = router.classify(user_input)
        assert result.tier == Tier.COMPLEX
        assert result.security_override is True

    def test_security_override_beats_medium_keywords(
        self, router: RuleRouter
    ) -> None:
        """Even if request has MEDIUM keywords, security wins."""
        user_input = "Refactor the password hashing function"
        result = router.classify(user_input)
        assert result.tier == Tier.COMPLEX
        assert result.security_override is True


# ── Simple Tier Tests ──


class TestSimpleTier:
    """Lightweight tasks should route to SIMPLE."""

    @pytest.mark.parametrize(
        "user_input",
        [
            "Format this Python function to follow PEP 8",
            "Add type hints to this function",
            "Add a docstring to this class",
            "Fix indentation in this file",
            "Convert to f-string",
            "Sort imports in this file",
            "Remove unused imports",
            "Generate a dataclass for User with name and email",
        ],
    )
    def test_simple_tasks(self, router: RuleRouter, user_input: str) -> None:
        result = router.classify(user_input)
        assert result.tier == Tier.SIMPLE, (
            f"Simple request '{user_input}' was routed to {result.tier}. "
            f"Matched: {result.matched_rules}"
        )
        assert result.security_override is False


# ── Medium Tier Tests ──


class TestMediumTier:
    """Standard coding tasks should route to MEDIUM."""

    @pytest.mark.parametrize(
        "user_input",
        [
            "Write unit tests for the PaymentService class",
            "Refactor this function to use the strategy pattern",
            "Fix this bug in the data processor",
            "Debug this KeyError in the CSV parser",
            "Add error handling to the API client",
            "Implement this function to calculate tax",
            "Optimize this database query",
        ],
    )
    def test_medium_tasks(self, router: RuleRouter, user_input: str) -> None:
        result = router.classify(user_input)
        assert result.tier == Tier.MEDIUM, (
            f"Medium request '{user_input}' was routed to {result.tier}. "
            f"Matched: {result.matched_rules}"
        )


# ── Complex Tier Tests ──


class TestComplexTier:
    """Architectural and system-level tasks should route to COMPLEX."""

    @pytest.mark.parametrize(
        "user_input",
        [
            "Review the architecture of this project and suggest improvements",
            "Design a system for real-time data processing",
            "Implement a complete REST API with middleware and error handling",
            "Set up a CI CD pipeline for this project",
            "Design the database schema for a multi-tenant application",
        ],
    )
    def test_complex_tasks(
        self, router: RuleRouter, user_input: str
    ) -> None:
        result = router.classify(user_input)
        assert result.tier == Tier.COMPLEX, (
            f"Complex request '{user_input}' was routed to {result.tier}. "
            f"Matched: {result.matched_rules}"
        )


# ── Scope Elevation Tests ──


class TestScopeElevation:
    """Scope signals should elevate tier classification."""

    def test_simple_elevated_to_medium_by_src_reference(
        self, router: RuleRouter
    ) -> None:
        user_input = "Format all files in src/ directory"
        result = router.classify(user_input)
        assert result.tier in (Tier.MEDIUM, Tier.COMPLEX), (
            f"Scope elevation failed for '{user_input}': {result.tier}"
        )

    def test_medium_elevated_to_complex_by_project_scope(
        self, router: RuleRouter
    ) -> None:
        user_input = "Refactor the entire project to use async/await"
        result = router.classify(user_input)
        assert result.tier == Tier.COMPLEX


# ── Edge Cases ──


class TestEdgeCases:
    """Edge cases and default behavior."""

    def test_empty_request_returns_default(self, router: RuleRouter) -> None:
        result = router.classify("")
        assert result.tier == Tier.MEDIUM  # default tier
        assert result.confidence < 0.5

    def test_unrecognized_request_returns_default(
        self, router: RuleRouter
    ) -> None:
        result = router.classify("Tell me about the weather today")
        assert result.tier == Tier.MEDIUM
        assert result.confidence < 0.5

    def test_case_insensitivity(self, router: RuleRouter) -> None:
        result1 = router.classify("FORMAT this code")
        result2 = router.classify("format this code")
        assert result1.tier == result2.tier

    def test_model_mapping(self, router: RuleRouter) -> None:
        assert router.get_model_for_tier(Tier.SIMPLE) == "gemma4:e4b"
        assert router.get_model_for_tier(Tier.MEDIUM) == "gemma4:26b"
        assert (
            router.get_model_for_tier(Tier.COMPLEX)
            == "claude-sonnet-4-20250514"
        )

    def test_routing_result_summary(self, router: RuleRouter) -> None:
        result = router.classify("Check for SQL injection")
        summary = result.summary()
        assert "COMPLEX" in summary
        assert "SECURITY OVERRIDE" in summary


# ── Config Reload Test ──


class TestConfigReload:
    """Router should support hot-reloading configuration."""

    def test_reload_does_not_crash(self, router: RuleRouter) -> None:
        router.reload_config()
        # Should still work after reload
        result = router.classify("Format this code")
        assert result.tier == Tier.SIMPLE
