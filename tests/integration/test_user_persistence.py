"""
PostgreSQL persistence for users, credentials, 2FA backup codes, refresh tokens and
clinical profiles, on a database built by the real Alembic migrations (0001 + 0002).
Skipped automatically when Docker is unavailable.
"""

import os
import subprocess
import sys
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.rxguard.auth.hasher import hash_password
from src.rxguard.auth.store import SqlAuthStore, UserExistsError
from src.rxguard.core.contracts.user_context import UserAllergyRecord, UserConditionRecord, UserContext
from src.rxguard.database.connection import create_engine, create_session_factory
from src.rxguard.users.profile_store import SqlProfileStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")


def alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "RXGUARD_DATABASE_URL": url}
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def migrated_url() -> Iterator[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as container:
        url = container.get_connection_url().replace("postgresql://", "postgresql+asyncpg://", 1)
        upgrade = alembic(url, "upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stderr
        yield url


def test_migrations_match_models_and_downgrade_cleanly(migrated_url: str) -> None:
    check = alembic(migrated_url, "check")
    assert check.returncode == 0, check.stdout + check.stderr  # no drift between models.py and migrations
    assert alembic(migrated_url, "downgrade", "0001").returncode == 0
    assert alembic(migrated_url, "upgrade", "head").returncode == 0


@pytest.mark.asyncio
async def test_auth_store_persists_users_codes_and_refresh_tokens(migrated_url: str) -> None:
    engine = create_engine(migrated_url)
    try:
        store = SqlAuthStore(create_session_factory(engine))
        user = await store.create("pat", None, hash_password("Secret-Passw0rd"))
        with pytest.raises(UserExistsError):
            await store.create("pat", None, hash_password("x"))
        assert user.roles == ["ROLE_USER"] and len(user.user_id) == 36

        # A second store instance (process restart) sees the same data.
        fresh = SqlAuthStore(create_session_factory(engine))
        loaded = await fresh.get_by_username("pat")
        assert loaded is not None and loaded.user_id == user.user_id
        assert (await fresh.get_by_id(user.user_id)) is not None
        assert await fresh.get_by_id("not-a-uuid") is None

        await fresh.begin_totp_setup(user.user_id, "JBSWY3DPEHPK3PXP", [hash_password("AAAA-BBBB")])
        await fresh.enable_totp(user.user_id)
        reloaded = await store.get_by_id(user.user_id)
        assert reloaded is not None and reloaded.totp_enabled and reloaded.totp_secret == "JBSWY3DPEHPK3PXP"
        assert await store.consume_backup_code(user.user_id, "AAAA-BBBB") is True
        assert await store.consume_backup_code(user.user_id, "AAAA-BBBB") is False

        expires = datetime.now(UTC) + timedelta(days=1)
        await store.store_refresh_token("jti-1", user.user_id, expires)
        assert await fresh.rotate_refresh_token("jti-1", user.user_id) == "rotated"
        assert await fresh.rotate_refresh_token("jti-1", user.user_id) == "reused"
        assert await fresh.rotate_refresh_token("jti-unknown", user.user_id) == "unknown"
        await store.store_refresh_token("jti-2", user.user_id, expires)
        await store.revoke_all_refresh_tokens(user.user_id)
        assert await store.rotate_refresh_token("jti-2", user.user_id) == "reused"
        await store.store_refresh_token("jti-old", user.user_id, datetime.now(UTC) - timedelta(seconds=1))
        assert await store.rotate_refresh_token("jti-old", user.user_id) == "unknown"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_store_round_trip_and_wipe(migrated_url: str) -> None:
    engine = create_engine(migrated_url)
    try:
        auth = SqlAuthStore(create_session_factory(engine))
        user = await auth.create("quinn", "quinn@example.org", hash_password("Secret-Passw0rd"))
        profiles = SqlProfileStore(create_session_factory(engine))
        saved = await profiles.save(
            UserContext(
                user_id=user.user_id,
                roles=["ROLE_USER"],
                active_medications=["Warfarin", "Metformin", "Warfarin"],
                allergies=[UserAllergyRecord(substance_name="Penicillin", severity="SEVERE_ANAPHYLAXIS")],
                conditions=[UserConditionRecord(condition_name="CKD stage 4", icd10_code="N18.4")],
            )
        )
        assert sorted(saved.active_medications) == ["Metformin", "Warfarin"]
        assert saved.allergies[0].substance_name == "Penicillin" and saved.allergies[0].allergy_id
        assert saved.conditions[0].icd10_code == "N18.4"

        replaced = await profiles.save(saved.model_copy(update={"active_medications": ["Lisinopril"]}))
        assert replaced.active_medications == ["Lisinopril"]
        assert len(replaced.allergies) == 1  # replaced, not duplicated

        assert await profiles.get("not-a-uuid") is None
        with pytest.raises(ValueError):
            await profiles.save(saved.model_copy(update={"user_id": "00000000-0000-0000-0000-000000000000"}))
        assert await profiles.delete(user.user_id) is True
        wiped = await profiles.get(user.user_id)
        assert wiped is not None and wiped.active_medications == [] and wiped.allergies == []
        assert await profiles.delete("not-a-uuid") is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rate_limit_counters_are_shared_and_survive_restarts(migrated_url: str) -> None:
    from src.rxguard.auth.rate_limit import LoginRateLimiter, RequestLimiter, SqlCounters

    engine = create_engine(migrated_url)
    try:
        # Two limiters (two workers, or before and after a restart) see the same counts.
        first = RequestLimiter(SqlCounters(create_session_factory(engine)))
        second = RequestLimiter(SqlCounters(create_session_factory(engine)))
        assert await first.hit("chat|203.0.113.7", 2, 60) is None
        assert await second.hit("chat|203.0.113.7", 2, 60) is None
        assert (await first.hit("chat|203.0.113.7", 2, 60) or 0) > 0

        login = LoginRateLimiter(
            max_failures=2, window_seconds=900, counters=SqlCounters(create_session_factory(engine))
        )
        await login.record_failure("pat|1.2.3.4")
        await login.record_failure("pat|1.2.3.4")
        assert await login.retry_after("pat|1.2.3.4") > 0
        await login.reset("pat|1.2.3.4")
        assert await login.retry_after("pat|1.2.3.4") == 0
    finally:
        await engine.dispose()
