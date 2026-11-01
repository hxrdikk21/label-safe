"""
Authentication and security package.
Includes Argon2id password hashing, JWT token management, and TOTP 2FA.
"""

from .hasher import hash_password, needs_rehash, verify_password
from .jwt import (
    AuthError,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from .two_factor import (
    generate_backup_codes,
    generate_totp_code,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
)

__all__ = [
    "AuthError",
    "TokenPayload",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "generate_backup_codes",
    "generate_totp_code",
    "generate_totp_secret",
    "get_totp_uri",
    "hash_password",
    "needs_rehash",
    "verify_password",
    "verify_totp_code",
]
