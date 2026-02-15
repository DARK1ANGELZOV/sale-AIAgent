"""Authentication, user profile, and chat sharing persistence service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.constants import UTC_TIMEZONE

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(slots=True)
class AuthUser:
    """Authenticated user DTO."""

    id: int
    email: str
    display_name: str
    settings: dict[str, Any]
    created_at: datetime


@dataclass(slots=True)
class SharedChatSnapshot:
    """Shared chat payload DTO."""

    title: str
    messages: list[dict[str, Any]]
    created_at: datetime
    owner_display_name: str


class AuthService:
    """Simple SQLite-backed auth/profile/share service."""

    def __init__(self, db_path: Path, session_ttl_hours: int = 168) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_ttl = timedelta(hours=session_ttl_hours)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._db_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        password_salt TEXT NOT NULL,
                        settings_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sessions (
                        token TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS shared_chats (
                        token TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        messages_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

    async def register(
        self, email: str, password: str, display_name: str | None = None
    ) -> tuple[str, AuthUser]:
        return await asyncio.to_thread(self._register_sync, email, password, display_name)

    def _register_sync(
        self, email: str, password: str, display_name: str | None = None
    ) -> tuple[str, AuthUser]:
        normalized_email = email.strip().lower()
        if not EMAIL_REGEX.match(normalized_email):
            raise ValueError("Некорректный email")
        if len(password) < 8:
            raise ValueError("Пароль должен быть не короче 8 символов")

        now = datetime.now(tz=UTC_TIMEZONE)
        display = (display_name or normalized_email.split("@")[0]).strip()[:80] or "User"
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password=password, salt=salt)

        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                cursor.execute(
                    """
                    INSERT INTO users (email, display_name, password_hash, password_salt, settings_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_email,
                        display,
                        password_hash,
                        salt,
                        json.dumps({}),
                        now.isoformat(),
                    ),
                )
                user_id = int(cursor.lastrowid)
                token = self._create_session(cursor=cursor, user_id=user_id, now=now)
                connection.commit()
                user = AuthUser(
                    id=user_id,
                    email=normalized_email,
                    display_name=display,
                    settings={},
                    created_at=now,
                )
                return token, user
            except sqlite3.IntegrityError as exc:
                if "users.email" in str(exc):
                    raise ValueError("Пользователь с таким email уже существует") from exc
                raise
            finally:
                connection.close()

    async def login(self, email: str, password: str) -> tuple[str, AuthUser]:
        return await asyncio.to_thread(self._login_sync, email, password)

    def _login_sync(self, email: str, password: str) -> tuple[str, AuthUser]:
        normalized_email = email.strip().lower()
        now = datetime.now(tz=UTC_TIMEZONE)

        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                row = cursor.execute(
                    """
                    SELECT id, email, display_name, password_hash, password_salt, settings_json, created_at
                    FROM users
                    WHERE email = ?
                    """,
                    (normalized_email,),
                ).fetchone()
                if not row:
                    raise ValueError("Неверный email или пароль")

                expected_hash = str(row["password_hash"])
                actual_hash = self._hash_password(password=password, salt=str(row["password_salt"]))
                if not secrets.compare_digest(expected_hash, actual_hash):
                    raise ValueError("Неверный email или пароль")

                token = self._create_session(cursor=cursor, user_id=int(row["id"]), now=now)
                connection.commit()
                user = self._row_to_user(row=row)
                return token, user
            finally:
                connection.close()

    async def logout(self, token: str) -> None:
        await asyncio.to_thread(self._logout_sync, token)

    def _logout_sync(self, token: str) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
                connection.commit()
            finally:
                connection.close()

    async def get_user_by_token(self, token: str) -> AuthUser | None:
        return await asyncio.to_thread(self._get_user_by_token_sync, token)

    def _get_user_by_token_sync(self, token: str) -> AuthUser | None:
        now = datetime.now(tz=UTC_TIMEZONE)
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                row = cursor.execute(
                    """
                    SELECT
                        u.id, u.email, u.display_name, u.settings_json, u.created_at,
                        s.expires_at
                    FROM sessions s
                    JOIN users u ON u.id = s.user_id
                    WHERE s.token = ?
                    """,
                    (token,),
                ).fetchone()
                if not row:
                    return None

                expires_at = datetime.fromisoformat(str(row["expires_at"]))
                if expires_at < now:
                    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    connection.commit()
                    return None
                return self._row_to_user(row=row)
            finally:
                connection.close()

    async def update_profile(
        self,
        user_id: int,
        display_name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> AuthUser:
        return await asyncio.to_thread(
            self._update_profile_sync,
            user_id,
            display_name,
            settings,
        )

    def _update_profile_sync(
        self,
        user_id: int,
        display_name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> AuthUser:
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.cursor()
                row = cursor.execute(
                    "SELECT id, email, display_name, settings_json, created_at FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
                if not row:
                    raise ValueError("Пользователь не найден")

                next_display = str(row["display_name"])
                if display_name is not None:
                    candidate = display_name.strip()
                    if not candidate:
                        raise ValueError("display_name не может быть пустым")
                    next_display = candidate[:80]

                current_settings = self._parse_settings(str(row["settings_json"]))
                next_settings = current_settings
                if settings is not None:
                    next_settings = {**current_settings, **settings}

                cursor.execute(
                    """
                    UPDATE users
                    SET display_name = ?, settings_json = ?
                    WHERE id = ?
                    """,
                    (next_display, json.dumps(next_settings), user_id),
                )
                connection.commit()
                updated_row = cursor.execute(
                    "SELECT id, email, display_name, settings_json, created_at FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
                if not updated_row:
                    raise ValueError("Пользователь не найден")
                return self._row_to_user(updated_row)
            finally:
                connection.close()

    async def create_share(
        self,
        user_id: int,
        title: str,
        messages: list[dict[str, Any]],
    ) -> str:
        return await asyncio.to_thread(self._create_share_sync, user_id, title, messages)

    def _create_share_sync(
        self,
        user_id: int,
        title: str,
        messages: list[dict[str, Any]],
    ) -> str:
        share_token = secrets.token_urlsafe(12)
        now = datetime.now(tz=UTC_TIMEZONE).isoformat()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    """
                    INSERT INTO shared_chats (token, user_id, title, messages_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        share_token,
                        user_id,
                        title.strip()[:120] or "Shared chat",
                        json.dumps(messages, ensure_ascii=False),
                        now,
                    ),
                )
                connection.commit()
                return share_token
            finally:
                connection.close()

    async def get_shared_chat(self, token: str) -> SharedChatSnapshot | None:
        return await asyncio.to_thread(self._get_shared_chat_sync, token)

    def _get_shared_chat_sync(self, token: str) -> SharedChatSnapshot | None:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    """
                    SELECT s.title, s.messages_json, s.created_at, u.display_name
                    FROM shared_chats s
                    JOIN users u ON u.id = s.user_id
                    WHERE s.token = ?
                    """,
                    (token,),
                ).fetchone()
                if not row:
                    return None
                return SharedChatSnapshot(
                    title=str(row["title"]),
                    messages=self._parse_messages(str(row["messages_json"])),
                    created_at=datetime.fromisoformat(str(row["created_at"])),
                    owner_display_name=str(row["display_name"]),
                )
            finally:
                connection.close()

    def _create_session(self, cursor: sqlite3.Cursor, user_id: int, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = now + self._session_ttl
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cursor.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, expires_at.isoformat(), now.isoformat()),
        )
        return token

    def _hash_password(self, password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        )
        return digest.hex()

    def _row_to_user(self, row: sqlite3.Row) -> AuthUser:
        return AuthUser(
            id=int(row["id"]),
            email=str(row["email"]),
            display_name=str(row["display_name"]),
            settings=self._parse_settings(str(row["settings_json"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _parse_settings(self, raw_json: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_json)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _parse_messages(self, raw_json: str) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(raw_json)
            return parsed if isinstance(parsed, list) else []
        except Exception:  # noqa: BLE001
            return []
