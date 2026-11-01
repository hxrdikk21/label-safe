"""
Password hashing and verification services.
Uses industry-standard Argon2id cryptographic password hashing.
"""

import argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = argon2.PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=1,
    hash_len=32,
    type=argon2.Type.ID,
)


def hash_password(plain_password: str) -> str:
    """Hashes a plaintext password using Argon2id."""
    if not plain_password:
        raise ValueError("Password cannot be empty")
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plaintext password against an Argon2id hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Checks whether the password hash needs to be upgraded to newer security parameters."""
    try:
        return _hasher.check_needs_rehash(hashed_password)
    except Exception:
        return True
