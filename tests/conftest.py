"""Unit tests run on the offline model doubles; set before any Settings is created."""

import os

os.environ.setdefault("MODEL_MODE", "fake")
os.environ.setdefault("LLM_BACKEND", "template")
# In-memory stores unless a test opts in; an empty value also overrides DATABASE_URL in a local .env.
os.environ.setdefault("DATABASE_URL", "")
# Curated rulebook only: generated rules (make rules) vary per machine.
os.environ.setdefault("RXGUARD_GENERATED_RULES_DIR", "/nonexistent-rxguard-generated-rules")
# Every test request comes from one client ("testclient"); per-IP limits are tested on purpose in
# tests/security/test_rate_limit.py, so the suite as a whole runs effectively unlimited.
for _limit in ("CHAT", "EXPLAIN", "ANALYZE", "SEARCH"):
    os.environ.setdefault(f"RATE_LIMIT_{_limit}_PER_MINUTE", "1000000")
os.environ.setdefault("RATE_LIMIT_REGISTER_PER_HOUR", "1000000")
