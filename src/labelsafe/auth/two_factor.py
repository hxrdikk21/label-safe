"""
Two-Factor Authentication (2FA) engine conforming to RFC 6238 (TOTP).
Pure standard-library implementation of Time-Based One-Time Passwords and recovery codes.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

from src.labelsafe.core.config import get_settings


def generate_totp_secret() -> str:
    """
    Generates a secure, cryptographically random base32-encoded secret key.
    32 base32 characters = 160 bits of entropy (RFC 6238 standard).
    """
    # 20 raw bytes = 160 bits
    raw_bytes = secrets.token_bytes(20)
    return base64.b32encode(raw_bytes).decode("ascii").rstrip("=")


def generate_totp_code(
    secret: str,
    timestamp: int | None = None,
    interval: int = 30,
    digits: int = 6,
) -> str:
    """
    Computes the 6-digit TOTP code for a given timestamp conforming to RFC 6238 / RFC 4226.
    """
    if timestamp is None:
        timestamp = int(time.time())

    # Calculate time counter
    time_counter = timestamp // interval

    # Normalize base32 secret with appropriate padding
    clean_secret = secret.strip().replace(" ", "").upper()
    missing_padding = len(clean_secret) % 8
    if missing_padding:
        clean_secret += "=" * (8 - missing_padding)

    try:
        key = base64.b32decode(clean_secret, casefold=True)
    except Exception as e:
        raise ValueError(f"Invalid base32 secret: {e}") from e

    # Pack counter as big-endian 8-byte unsigned integer
    counter_bytes = struct.pack(">Q", time_counter)

    # Compute HMAC-SHA1
    hmac_digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()

    # Dynamic truncation
    offset = hmac_digest[-1] & 0x0F
    code_int = struct.unpack(">I", hmac_digest[offset : offset + 4])[0] & 0x7FFFFFFF
    token = code_int % (10**digits)

    # Format with leading zeros
    return f"{token:0{digits}d}"


def verify_totp_code(
    secret: str,
    code: str,
    window: int = 1,
    interval: int = 30,
    timestamp: int | None = None,
) -> bool:
    """
    Verifies a user-submitted TOTP code against the secret key.
    Supports a configurable window tolerance for clock drift (default 1 step = +/- 30 seconds).
    """
    if not code or not secret:
        return False

    clean_code = code.strip().replace(" ", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False

    if timestamp is None:
        timestamp = int(time.time())

    # Check window [-window, +window]
    for step_offset in range(-window, window + 1):
        check_time = timestamp + (step_offset * interval)
        valid_code = generate_totp_code(secret, timestamp=check_time, interval=interval, digits=6)
        if hmac.compare_digest(clean_code, valid_code):
            return True

    return False


def get_totp_uri(
    secret: str,
    account_name: str,
    issuer: str | None = None,
) -> str:
    """
    Builds the standard otpauth:// URI for authenticator applications (e.g. Google Authenticator).
    """
    settings = get_settings()
    app_issuer = issuer or settings.totp_issuer
    encoded_issuer = urllib.parse.quote(app_issuer)
    encoded_account = urllib.parse.quote(account_name)

    return (
        f"otpauth://totp/{encoded_issuer}:{encoded_account}"
        f"?secret={secret}&issuer={encoded_issuer}&algorithm=SHA1&digits=6&period=30"
    )


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generates a list of one-time backup recovery codes (formatted as XXXX-XXXX)."""
    codes: list[str] = []
    for _ in range(count):
        token = secrets.token_hex(4).upper()
        formatted = f"{token[:4]}-{token[4:]}"
        codes.append(formatted)
    return codes
