"""
Security Unit Test Suite for Password Hashing and JWT Management (Phase 5).
Tests Argon2id hashing, password verification, JWT issuance, claims, and expiration.
"""

from datetime import timedelta

import pytest

from src.rxguard.auth.hasher import hash_password, needs_rehash, verify_password
from src.rxguard.auth.jwt import (
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_token,
)


class TestPasswordHashing:
    """Tests for Argon2id password hashing and verification."""

    def test_hash_and_verify_success(self):
        password = "ClinicalSecretPassword!2026"
        hashed = hash_password(password)
        assert hashed.startswith("$argon2id$")
        assert verify_password(password, hashed) is True

    def test_verify_failure_with_wrong_password(self):
        password = "CorrectPassword123"
        hashed = hash_password(password)
        assert verify_password("WrongPassword456", hashed) is False

    def test_empty_password_rejection(self):
        with pytest.raises(ValueError):
            hash_password("")
        assert verify_password("", "some_hash") is False
        assert verify_password("pass", "") is False

    def test_needs_rehash(self):
        password = "TestPassword"
        hashed = hash_password(password)
        assert needs_rehash(hashed) is False
        assert needs_rehash("corrupted_hash") is True


class TestJWTTokenManagement:
    """Tests for JWT token creation, decoding, and expiration."""

    def test_create_and_decode_access_token(self):
        user_id = "USER-12345"
        roles = ["ROLE_USER", "ROLE_ADMIN"]
        token = create_access_token(user_id=user_id, roles=roles)

        payload = decode_token(token)
        assert payload.sub == user_id
        assert payload.roles == roles
        assert payload.type == "access"
        assert payload.exp > payload.iat

    def test_create_and_decode_refresh_token(self):
        user_id = "USER-67890"
        token = create_refresh_token(user_id=user_id)

        payload = decode_token(token)
        assert payload.sub == user_id
        assert payload.type == "refresh"

    def test_expired_token_raises_auth_error(self):
        # Create token that expired 1 second ago
        token = create_access_token(
            user_id="USER-EXPIRED",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(AuthError, match="expired"):
            decode_token(token)

    def test_invalid_tampered_token_raises_auth_error(self):
        token = create_access_token(user_id="USER-VALID")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthError, match="Invalid token"):
            decode_token(tampered)
