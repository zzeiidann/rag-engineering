import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConflictError(ValueError):
    pass


class AuthRepository:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS departments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('guest','client','internal')),
                    client_id TEXT,
                    department_id TEXT REFERENCES departments(id) ON DELETE RESTRICT,
                    permissions TEXT NOT NULL DEFAULT '[]',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tokens_hash ON api_tokens(token_hash);
                CREATE INDEX IF NOT EXISTS idx_users_department ON users(department_id);
                """
            )

    def bootstrap_admin(self, username: str, password: str) -> None:
        if not username or not password:
            return
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM users WHERE is_admin=1").fetchone():
                return
            now = utc_now().isoformat()
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, 'internal', NULL, NULL, ?, 1, 1, ?, ?)",
                (
                    uuid4().hex,
                    username.lower().strip(),
                    generate_password_hash(password, method="scrypt"),
                    json.dumps(["documents:write", "retrieval:debug", "internal:read:all"]),
                    now,
                    now,
                ),
            )

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=? AND active=1", (username.lower().strip(),)
            ).fetchone()
        if row is None or not check_password_hash(row["password_hash"], password):
            return None
        return self.serialize_user(row)

    def serialize_user(self, row: sqlite3.Row, include_admin: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "client_id": row["client_id"],
            "department": row["department_id"],
            "permissions": json.loads(row["permissions"]),
            "active": bool(row["active"]),
        }
        if include_admin:
            result["is_admin"] = bool(row["is_admin"])
            result["created_at"] = row["created_at"]
            result["updated_at"] = row["updated_at"]
        return result

    def principal(self, row: sqlite3.Row) -> dict[str, Any]:
        user = self.serialize_user(row, include_admin=False)
        return {
            "user_id": user["id"],
            "role": user["role"],
            "client_id": user["client_id"],
            "department": user["department"],
            "permissions": user["permissions"],
        }

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [self.serialize_user(row) for row in rows]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self.serialize_user(row) if row else None

    def validate_user(self, data: dict[str, Any]) -> dict[str, Any]:
        role = str(data.get("role", "")).strip()
        client_id = str(data.get("client_id") or "").strip() or None
        department = str(data.get("department") or "").strip() or None
        permissions = data.get("permissions", [])
        if role not in {"guest", "client", "internal"}:
            raise ValueError("Role must be guest, client, or internal")
        if not isinstance(permissions, list) or any(
            not isinstance(permission, str) or not permission.strip() for permission in permissions
        ):
            raise ValueError("Permissions must be a list of non-empty strings")
        permissions = sorted(set(permission.strip() for permission in permissions))
        if role == "client" and not client_id:
            raise ValueError("Client users require client_id")
        if role != "client" and client_id:
            raise ValueError("Only client users may have client_id")
        if role != "internal" and (department or permissions):
            raise ValueError("Only internal users may have department or permissions")
        if data.get("is_admin") and role != "internal":
            raise ValueError("Administrators must use the internal role")
        return {
            "role": role,
            "client_id": client_id,
            "department": department,
            "permissions": permissions,
            "is_admin": bool(data.get("is_admin", False)),
            "active": bool(data.get("active", True)),
        }

    def create_user(self, data: dict[str, Any]) -> dict[str, Any]:
        username = str(data.get("username", "")).lower().strip()
        password = str(data.get("password", ""))
        if len(username) < 3 or len(password) < 10:
            raise ValueError("Username needs 3 characters and password needs 10 characters")
        values = self.validate_user(data)
        now = utc_now().isoformat()
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id := uuid4().hex,
                        username,
                        generate_password_hash(password, method="scrypt"),
                        values["role"],
                        values["client_id"],
                        values["department"],
                        json.dumps(values["permissions"]),
                        int(values["is_admin"]),
                        int(values["active"]),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Username or department is invalid or already used") from exc
        return self.get_user(user_id) or {}

    def update_user(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        current = self.get_user(user_id)
        if current is None:
            raise KeyError(user_id)
        values = self.validate_user({**current, **data})
        username = str(data.get("username", current["username"])).lower().strip()
        if len(username) < 3:
            raise ValueError("Username needs at least 3 characters")
        password = data.get("password")
        if password is not None and len(str(password)) < 10:
            raise ValueError("Password needs at least 10 characters")
        assignments = (
            "username=?, role=?, client_id=?, department_id=?, permissions=?, "
            "is_admin=?, active=?, updated_at=?"
        )
        parameters: list[Any] = [
            username,
            values["role"],
            values["client_id"],
            values["department"],
            json.dumps(values["permissions"]),
            int(values["is_admin"]),
            int(values["active"]),
            utc_now().isoformat(),
        ]
        if password:
            assignments += ", password_hash=?"
            parameters.append(generate_password_hash(str(password), method="scrypt"))
        parameters.append(user_id)
        try:
            with self.connect() as connection:
                connection.execute(f"UPDATE users SET {assignments} WHERE id=?", parameters)
                if not values["active"] or password:
                    connection.execute(
                        "UPDATE api_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                        (utc_now().isoformat(), user_id),
                    )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Username or department is invalid or already used") from exc
        return self.get_user(user_id) or {}

    def list_departments(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT d.*, COUNT(u.id) AS user_count FROM departments d "
                "LEFT JOIN users u ON u.department_id=d.id GROUP BY d.id ORDER BY d.name"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_department(self, data: dict[str, Any]) -> dict[str, Any]:
        identifier = str(data.get("id", "")).lower().strip().replace(" ", "_")
        name = str(data.get("name", "")).strip()
        description = str(data.get("description", "")).strip()
        if not identifier.replace("_", "").isalnum() or not name:
            raise ValueError("Department ID and name are required")
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO departments VALUES (?, ?, ?, ?)",
                    (identifier, name, description, utc_now().isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Department ID or name already exists") from exc
        return next(item for item in self.list_departments() if item["id"] == identifier)

    def delete_department(self, identifier: str) -> None:
        try:
            with self.connect() as connection:
                cursor = connection.execute("DELETE FROM departments WHERE id=?", (identifier,))
                if cursor.rowcount != 1:
                    raise KeyError(identifier)
        except sqlite3.IntegrityError as exc:
            raise ConflictError("Department still has assigned users") from exc

    def issue_token(self, user_id: str, ttl_hours: int) -> tuple[str, str]:
        user = self.get_user(user_id)
        if user is None or not user["active"]:
            raise ValueError("User is inactive or does not exist")
        token = secrets.token_urlsafe(40)
        expires = utc_now() + timedelta(hours=ttl_hours)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO api_tokens VALUES (?, ?, ?, ?, NULL, ?)",
                (
                    uuid4().hex,
                    hashlib.sha256(token.encode()).hexdigest(),
                    user_id,
                    expires.isoformat(),
                    utc_now().isoformat(),
                ),
            )
        return token, expires.isoformat()

    def introspect(self, token: str) -> dict[str, Any] | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT u.* FROM api_tokens t JOIN users u ON u.id=t.user_id "
                "WHERE t.token_hash=? AND t.revoked_at IS NULL AND t.expires_at>? AND u.active=1",
                (digest, utc_now().isoformat()),
            ).fetchone()
        return self.principal(row) if row else None

    def revoke_user_tokens(self, user_id: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (utc_now().isoformat(), user_id),
            )
        return cursor.rowcount
