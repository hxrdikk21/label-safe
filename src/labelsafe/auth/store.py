"""
Credential, 2FA and refresh-token persistence.

``SqlAuthStore`` keeps users in the canonical PostgreSQL ``users`` table (plus
``user_backup_codes`` and ``refresh_tokens``); ``InMemoryAuthStore`` has the same
behaviour for tests and offline runs. Passwords and backup codes are stored only
as Argon2id hashes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.auth.hasher import verify_password
from src.labelsafe.database.models import RefreshTokenRecord, User, UserBackupCode


class UserExistsError(Exception):
    """Username (or email) is already registered."""


class AuthUser(BaseModel):
    user_id: str
    username: str
    email: str | None = None
    full_name: str | None = None
    password_hash: str
    roles: list[str] = Field(default_factory=lambda: ["ROLE_USER"])
    totp_secret: str | None = None
    totp_enabled: bool = False


class AuthStore(Protocol):
    async def get_by_username(self, username: str) -> AuthUser | None: ...

    async def get_by_id(self, user_id: str) -> AuthUser | None: ...

    async def create(
        self, username: str, email: str | None, password_hash: str, full_name: str | None = None
    ) -> AuthUser: ...

    async def begin_totp_setup(self, user_id: str, secret: str, backup_code_hashes: list[str]) -> None: ...

    async def enable_totp(self, user_id: str) -> None: ...

    async def consume_backup_code(self, user_id: str, code: str) -> bool: ...

    async def store_refresh_token(self, jti: str, user_id: str, expires_at: datetime) -> None: ...

    async def rotate_refresh_token(self, jti: str, user_id: str) -> str:
        """Revokes an active token. Returns ``"rotated"``, ``"reused"`` (already revoked) or ``"unknown"``."""
        ...

    async def revoke_all_refresh_tokens(self, user_id: str) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryAuthStore:
    def __init__(self) -> None:
        self._users: dict[str, AuthUser] = {}
        self._backup_codes: dict[str, list[tuple[str, bool]]] = {}
        self._refresh: dict[str, tuple[str, datetime, datetime | None]] = {}

    async def get_by_username(self, username: str) -> AuthUser | None:
        user = self._users.get(username)
        return user.model_copy() if user else None

    async def get_by_id(self, user_id: str) -> AuthUser | None:
        return await self.get_by_username(user_id)  # user_id == username in memory

    async def create(
        self, username: str, email: str | None, password_hash: str, full_name: str | None = None
    ) -> AuthUser:
        if username in self._users:
            raise UserExistsError(username)
        user = AuthUser(
            user_id=username, username=username, email=email, full_name=full_name, password_hash=password_hash
        )
        self._users[username] = user
        return user.model_copy()

    async def begin_totp_setup(self, user_id: str, secret: str, backup_code_hashes: list[str]) -> None:
        self._users[user_id].totp_secret = secret
        self._backup_codes[user_id] = [(h, False) for h in backup_code_hashes]

    async def enable_totp(self, user_id: str) -> None:
        self._users[user_id].totp_enabled = True

    async def consume_backup_code(self, user_id: str, code: str) -> bool:
        codes = self._backup_codes.get(user_id, [])
        for index, (code_hash, used) in enumerate(codes):
            if not used and verify_password(code, code_hash):
                codes[index] = (code_hash, True)
                return True
        return False

    async def store_refresh_token(self, jti: str, user_id: str, expires_at: datetime) -> None:
        self._refresh[jti] = (user_id, expires_at, None)

    async def rotate_refresh_token(self, jti: str, user_id: str) -> str:
        record = self._refresh.get(jti)
        if record is None or record[0] != user_id:
            return "unknown"
        if record[2] is not None:
            return "reused"
        if record[1] <= _now():
            return "unknown"
        self._refresh[jti] = (record[0], record[1], _now())
        return "rotated"

    async def revoke_all_refresh_tokens(self, user_id: str) -> None:
        for jti, (uid, expires_at, revoked_at) in list(self._refresh.items()):
            if uid == user_id and revoked_at is None:
                self._refresh[jti] = (uid, expires_at, _now())


def _uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return None


class SqlAuthStore:
    """PostgreSQL-backed store on Mudit's ``users`` table (``user_id`` is a UUID)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _to_model(row: User) -> AuthUser:
        return AuthUser(
            user_id=str(row.user_id),
            username=row.username,
            email=row.email,
            full_name=getattr(row, "full_name", None),
            password_hash=row.password_hash,
            roles=[row.role],
            totp_secret=row.totp_secret,
            totp_enabled=row.is_2fa_enabled,
        )

    async def get_by_username(self, username: str) -> AuthUser | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(User).where(User.username == username))
            return self._to_model(row) if row else None

    async def get_by_id(self, user_id: str) -> AuthUser | None:
        uid = _uuid(user_id)
        if uid is None:
            return None
        async with self._session_factory() as session:
            row = await session.get(User, uid)
            return self._to_model(row) if row else None

    async def create(
        self, username: str, email: str | None, password_hash: str, full_name: str | None = None
    ) -> AuthUser:
        row = User(
            username=username, email=email, password_hash=password_hash, role="ROLE_USER", full_name=full_name
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            raise UserExistsError(username) from exc
        return self._to_model(row)

    async def begin_totp_setup(self, user_id: str, secret: str, backup_code_hashes: list[str]) -> None:
        uid = uuid.UUID(user_id)
        async with self._session_factory() as session, session.begin():
            await session.execute(update(User).where(User.user_id == uid).values(totp_secret=secret))
            existing = await session.scalars(select(UserBackupCode).where(UserBackupCode.user_id == uid))
            for code in existing:
                await session.delete(code)
            session.add_all(UserBackupCode(user_id=uid, code_hash=h) for h in backup_code_hashes)

    async def enable_totp(self, user_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(User).where(User.user_id == uuid.UUID(user_id)).values(is_2fa_enabled=True)
            )

    async def consume_backup_code(self, user_id: str, code: str) -> bool:
        uid = _uuid(user_id)
        if uid is None:
            return False
        async with self._session_factory() as session, session.begin():
            unused = await session.scalars(
                select(UserBackupCode)
                .where(UserBackupCode.user_id == uid, UserBackupCode.used_at.is_(None))
                .with_for_update()
            )
            for row in unused:
                if verify_password(code, row.code_hash):
                    row.used_at = _now()
                    return True
        return False

    async def store_refresh_token(self, jti: str, user_id: str, expires_at: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(RefreshTokenRecord(jti=jti, user_id=uuid.UUID(user_id), expires_at=expires_at))

    async def rotate_refresh_token(self, jti: str, user_id: str) -> str:
        uid = _uuid(user_id)
        async with self._session_factory() as session, session.begin():
            row = await session.get(RefreshTokenRecord, jti, with_for_update=True)
            if row is None or uid is None or row.user_id != uid:
                return "unknown"
            if row.revoked_at is not None:
                return "reused"
            if row.expires_at <= _now():
                return "unknown"
            row.revoked_at = _now()
            return "rotated"

    async def revoke_all_refresh_tokens(self, user_id: str) -> None:
        uid = _uuid(user_id)
        if uid is None:
            return
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(RefreshTokenRecord)
                .where(RefreshTokenRecord.user_id == uid, RefreshTokenRecord.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
