"""SHA-256 fingerprinting helpers used for provenance and idempotent ingestion."""

import hashlib
import json
import re
import uuid
from typing import Any, Final

_WHITESPACE = re.compile(r"[ \t\r\f\v]+")

LABELSAFE_NAMESPACE: Final = uuid.UUID("6f1c2b0e-7d4a-5e8b-9c3d-2a1b0c9d8e7f")


def sha256_hex(data: str | bytes) -> str:
    """Returns the hex SHA-256 digest of raw text or bytes."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def normalize_text(text: str) -> str:
    """Collapses horizontal whitespace and trims lines so fingerprints ignore formatting noise."""
    lines = (_WHITESPACE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def fingerprint_text(text: str) -> str:
    """Returns the SHA-256 digest of whitespace-normalized text."""
    return sha256_hex(normalize_text(text))


def fingerprint_json(payload: Any) -> str:
    """Returns the SHA-256 digest of a canonical (sorted, compact) JSON serialization."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256_hex(canonical)


def stable_uuid(*parts: str) -> uuid.UUID:
    """Derives a deterministic UUIDv5 so re-ingestion yields identical primary keys."""
    return uuid.uuid5(LABELSAFE_NAMESPACE, "|".join(parts))
