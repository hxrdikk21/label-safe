"""
Security Unit Test Suite for User Clinical Data Isolation & Context Guard (Phase 6).
Tests context isolation between users, access denial on cross-user queries, and LLM prompt sanitization.
"""

import pytest

from src.rxguard.core.contracts.user_context import (
    UserAllergyRecord,
    UserConditionRecord,
)
from src.rxguard.users.context_guard import AccessDeniedError, ContextGuard
from src.rxguard.users.service import UserService


class TestUserContextIsolation:
    """Tests guaranteeing zero cross-user clinical context leakage."""

    @pytest.fixture
    def user_service(self):
        service = UserService()
        # Seed Alice (User 1)
        service.add_active_medication("USER-ALICE", "Warfarin 5mg")
        service.add_allergy_record(
            "USER-ALICE",
            UserAllergyRecord(substance_name="Penicillin", severity="SEVERE_ANAPHYLAXIS"),
        )
        service.add_condition_record(
            "USER-ALICE",
            UserConditionRecord(condition_name="Atrial Fibrillation", icd10_code="I48"),
        )

        # Seed Bob (User 2)
        service.add_active_medication("USER-BOB", "Metformin 500mg")
        return service

    def test_user_self_access_allowed(self, user_service):
        assert ContextGuard.validate_access("USER-ALICE", "USER-ALICE", ["ROLE_USER"]) is True
        assert ContextGuard.validate_access("USER-BOB", "USER-BOB", ["ROLE_USER"]) is True

    def test_cross_user_access_strictly_forbidden(self, user_service):
        # Alice attempts to access Bob's medical context
        with pytest.raises(AccessDeniedError, match="Cross-user clinical data access forbidden"):
            ContextGuard.validate_access("USER-ALICE", "USER-BOB", ["ROLE_USER"])

        # Bob attempts to access Alice's medical context
        with pytest.raises(AccessDeniedError):
            ContextGuard.validate_access("USER-BOB", "USER-ALICE", ["ROLE_USER"])

    def test_admin_cross_user_access_restricted(self, user_service):
        # Even ROLE_ADMIN cannot access another user's unmasked profile through normal user routes
        with pytest.raises(AccessDeniedError):
            ContextGuard.validate_access("ADMIN-01", "USER-ALICE", ["ROLE_ADMIN"])

    def test_sanitize_context_for_prompt(self, user_service):
        alice_ctx = user_service.get_user_context("USER-ALICE")
        sanitized = ContextGuard.sanitize_context_for_prompt(alice_ctx)

        # Verify medical data is retained
        assert "Warfarin 5mg" in sanitized["active_medications"]
        assert sanitized["allergies"][0]["substance"] == "Penicillin"
        assert sanitized["conditions"][0]["code"] == "I48"

        # Verify internal account identifiers are absent
        assert "user_id" not in sanitized
        assert "roles" not in sanitized
        assert "password_hash" not in sanitized

    def test_clear_clinical_profile(self, user_service):
        assert user_service.clear_clinical_profile("USER-ALICE") is True
        assert user_service.get_user_context("USER-ALICE") is None
