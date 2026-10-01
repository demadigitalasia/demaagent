"""Durable internal identity mappings and safe audit metadata.

This module is intentionally storage-only. It does not expose HTTP routes, wire
Telegram, issue sessions, or import Mission Control server/control-plane code.
Callers must provide the SQLite database path explicitly; no live database path
or identity records are created by this module.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from typing import Any

from .tenant_boundary import (
    IdentityMapping,
    IdentityStatus,
    Role,
    validate_telegram_user_id,
)


SCHEMA_VERSION = 1
MAX_AUDIT_METADATA_BYTES = 4096
MAX_AUDIT_EVENTS_READ = 1000
_MAX_METADATA_DEPTH = 5
_MAX_METADATA_ENTRIES = 32
_MAX_METADATA_STRING_LENGTH = 256
_INTERNAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_AUDIT_LABEL_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_AUDIT_ACTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_.:@/-]{0,127}$")
_DIGIT_ID_RE = re.compile(r"^[0-9]{1,20}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|token|password|api[_-]?key|bearer|credential|private[_-]?key|"
    r"access[_-]?token|authorization|cookie|session|telegram[_-]?user[_-]?id|"
    r"raw[_-]?identity)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|"
    r"\bBearer\s+\S+|"
    r"(?:ghp|github_pat|sk|pk|rk|xox[baprs])[-_][A-Za-z0-9_-]{8,}|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    re.IGNORECASE,
)


class IdentityStoreError(RuntimeError):
    """Base error for durable identity-store failures."""


class IdentityStoreValidationError(ValueError):
    """Raised when input fails closed validation."""


class DuplicateIdentityMapping(IdentityStoreError):
    """Raised when a Telegram identity already has a mapping."""


class AmbiguousIdentityMapping(IdentityStoreError):
    """Raised when one internal user would span incompatible contexts."""


class PlatformAdminMappingError(IdentityStoreValidationError):
    """Raised when platform_admin is sent through the Telegram boundary."""


class AuditMetadataError(IdentityStoreValidationError):
    """Raised when audit metadata is unsafe, invalid, or too large."""


class MappingNotFound(IdentityStoreError):
    """Raised when a mutation targets an unknown Telegram identity."""


class SchemaVersionError(IdentityStoreError):
    """Raised when the database schema is newer or incompatible."""


@dataclass(frozen=True)
class IdentityRecord:
    """One persisted identity mapping, including immutable audit timestamps."""

    telegram_user_id: str
    user_id: str
    tenant_id: str
    role: Role
    status: IdentityStatus
    created_at: str
    updated_at: str

    def to_policy_mapping(self) -> IdentityMapping:
        """Return the pure-policy mapping represented by this record."""
        return IdentityMapping(
            telegram_user_id=self.telegram_user_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            role=self.role,
            status=self.status,
        )


@dataclass(frozen=True)
class AuditEvent:
    """Safe audit read model; raw Telegram IDs never appear in this model."""

    event_id: str
    timestamp: str
    action: str
    actor_type: str
    actor_id: str
    target_type: str
    identity_fingerprint: str
    result: str
    metadata: dict[str, Any]


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS identity_mappings (
        telegram_user_id TEXT PRIMARY KEY NOT NULL
            CHECK (
                typeof(telegram_user_id) = 'text'
                AND length(telegram_user_id) BETWEEN 1 AND 20
                AND telegram_user_id NOT GLOB '*[^0-9]*'
            ),
        user_id TEXT NOT NULL
            CHECK (
                length(user_id) BETWEEN 1 AND 128
                AND user_id NOT GLOB '*[^a-z0-9_-]*'
            ),
        tenant_id TEXT NOT NULL
            CHECK (
                length(tenant_id) BETWEEN 1 AND 128
                AND tenant_id NOT GLOB '*[^a-z0-9_-]*'
            ),
        role TEXT NOT NULL CHECK (role IN ('user', 'tenant_admin')),
        status TEXT NOT NULL CHECK (status IN ('active', 'pending', 'suspended', 'disabled')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_identity_mappings_user_id
        ON identity_mappings (user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id TEXT PRIMARY KEY NOT NULL,
        event_timestamp TEXT NOT NULL,
        action TEXT NOT NULL
            CHECK (
                length(action) BETWEEN 1 AND 64
                AND action NOT GLOB '*[^a-z0-9_.-]*'
            ),
        actor_type TEXT NOT NULL
            CHECK (
                length(actor_type) BETWEEN 1 AND 64
                AND actor_type NOT GLOB '*[^a-z0-9_.-]*'
            ),
        actor_id TEXT NOT NULL
            CHECK (
                length(actor_id) BETWEEN 1 AND 128
                AND actor_id NOT GLOB '*[^a-z0-9_.:@/-]*'
            ),
        target_type TEXT NOT NULL
            CHECK (
                length(target_type) BETWEEN 1 AND 64
                AND target_type NOT GLOB '*[^a-z0-9_.-]*'
            ),
        identity_fingerprint TEXT NOT NULL
            CHECK (
                length(identity_fingerprint) = 64
                AND identity_fingerprint NOT GLOB '*[^0-9a-f]*'
            ),
        result TEXT NOT NULL CHECK (result IN ('success', 'failure')),
        metadata_json TEXT NOT NULL CHECK (length(metadata_json) <= 4096)
    )
    """,
)

_EXPECTED_COLUMNS = {
    "identity_mappings": {
        "telegram_user_id",
        "user_id",
        "tenant_id",
        "role",
        "status",
        "created_at",
        "updated_at",
    },
    "audit_events": {
        "event_id",
        "event_timestamp",
        "action",
        "actor_type",
        "actor_id",
        "target_type",
        "identity_fingerprint",
        "result",
        "metadata_json",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fingerprint(telegram_user_id: str) -> str:
    return hashlib.sha256(telegram_user_id.encode("utf-8")).hexdigest()


def _validate_internal_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _INTERNAL_ID_RE.fullmatch(value) is None:
        raise IdentityStoreValidationError(
            f"{field_name} must be an explicit bounded identifier"
        )
    return value


def _validate_audit_label(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _AUDIT_LABEL_RE.fullmatch(value) is None:
        raise IdentityStoreValidationError(f"{field_name} must be a safe bounded label")
    return value


def _validate_actor_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or _AUDIT_ACTOR_ID_RE.fullmatch(value) is None
        or _DIGIT_ID_RE.fullmatch(value) is not None
    ):
        raise IdentityStoreValidationError("actor_id must be a safe internal identifier")
    return value


def _validate_metadata_value(value: Any, *, depth: int, forbidden_identity: str) -> None:
    if depth > _MAX_METADATA_DEPTH:
        raise AuditMetadataError("audit metadata nesting is too deep")
    if isinstance(value, Mapping):
        if len(value) > _MAX_METADATA_ENTRIES:
            raise AuditMetadataError("audit metadata object is too large")
        for key, child in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > _MAX_METADATA_STRING_LENGTH
                or _SENSITIVE_KEY_RE.search(key) is not None
            ):
                raise AuditMetadataError("audit metadata contains an unsafe key")
            _validate_metadata_value(child, depth=depth + 1, forbidden_identity=forbidden_identity)
        return
    if isinstance(value, list):
        if len(value) > _MAX_METADATA_ENTRIES:
            raise AuditMetadataError("audit metadata list is too large")
        for child in value:
            _validate_metadata_value(child, depth=depth + 1, forbidden_identity=forbidden_identity)
        return
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuditMetadataError("audit metadata must contain finite numbers")
        return
    if isinstance(value, str):
        if len(value) > _MAX_METADATA_STRING_LENGTH:
            raise AuditMetadataError("audit metadata string is too long")
        if value == forbidden_identity or _DIGIT_ID_RE.fullmatch(value) is not None:
            raise AuditMetadataError("raw identity values are not allowed in audit metadata")
        if _SECRET_VALUE_RE.search(value) is not None:
            raise AuditMetadataError("credential-shaped values are not allowed in audit metadata")
        return
    raise AuditMetadataError("audit metadata must be JSON-compatible")


def _serialize_metadata(metadata: Mapping[str, Any] | None, *, forbidden_identity: str) -> str:
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, Mapping):
        raise AuditMetadataError("audit_metadata must be a mapping")
    _validate_metadata_value(metadata, depth=0, forbidden_identity=forbidden_identity)
    try:
        serialized = json.dumps(
            metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AuditMetadataError("audit metadata is not serializable JSON") from exc
    if len(serialized.encode("utf-8")) > MAX_AUDIT_METADATA_BYTES:
        raise AuditMetadataError("audit metadata exceeds the bounded size")
    return serialized


def _row_to_record(row: sqlite3.Row) -> IdentityRecord:
    return IdentityRecord(
        telegram_user_id=row["telegram_user_id"],
        user_id=row["user_id"],
        tenant_id=row["tenant_id"],
        role=Role(row["role"]),
        status=IdentityStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class IdentityStore:
    """Small transactional SQLite store for internal identity mappings."""

    def __init__(self, connection: sqlite3.Connection, database_path: str | os.PathLike[str]):
        self._connection = connection
        self.database_path = os.fspath(database_path)
        self._lock = threading.RLock()
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise IdentityStoreError("identity store is closed")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._ensure_open()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _initialize_schema(self) -> None:
        with self._transaction():
            current_version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"database schema version {current_version} is newer than supported v{SCHEMA_VERSION}"
                )
            for statement in _SCHEMA_STATEMENTS:
                self._connection.execute(statement)
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._verify_schema()

    def _verify_schema(self) -> None:
        for table_name, expected_columns in _EXPECTED_COLUMNS.items():
            rows = self._connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            actual_columns = {row[1] for row in rows}
            if actual_columns != expected_columns:
                raise SchemaVersionError(f"incompatible schema for {table_name}")

    def close(self) -> None:
        if self._closed:
            return
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _coerce_mapping(
        self,
        telegram_user_id: Any,
        user_id: Any,
        tenant_id: Any,
        role: Any,
        status: Any,
    ) -> IdentityMapping:
        try:
            mapping = IdentityMapping(
                telegram_user_id=telegram_user_id,
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                status=status,
            )
        except ValueError as exc:
            raise IdentityStoreValidationError(str(exc)) from exc
        if mapping.role is Role.PLATFORM_ADMIN:
            raise PlatformAdminMappingError(
                "platform_admin is outside the Telegram identity boundary"
            )
        return mapping

    def _fetch_mapping_row(self, telegram_user_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT telegram_user_id, user_id, tenant_id, role, status, created_at, updated_at
            FROM identity_mappings
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()

    def _append_audit(
        self,
        *,
        action: str,
        actor_type: str,
        actor_id: str,
        target_type: str,
        telegram_user_id: str,
        result: str,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        action = _validate_audit_label(action, "action")
        actor_type = _validate_audit_label(actor_type, "actor_type")
        actor_id = _validate_actor_id(actor_id)
        target_type = _validate_audit_label(target_type, "target_type")
        if result not in {"success", "failure"}:
            raise IdentityStoreValidationError("result must be success or failure")
        metadata_json = _serialize_metadata(metadata, forbidden_identity=telegram_user_id)
        self._connection.execute(
            """
            INSERT INTO audit_events (
                event_id, event_timestamp, action, actor_type, actor_id,
                target_type, identity_fingerprint, result, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                _utc_now(),
                action,
                actor_type,
                actor_id,
                target_type,
                _fingerprint(telegram_user_id),
                result,
                metadata_json,
            ),
        )

    def add_mapping(
        self,
        telegram_user_id: Any,
        user_id: Any,
        tenant_id: Any,
        role: Any = Role.USER,
        status: Any = IdentityStatus.PENDING,
        *,
        actor_type: str = "system",
        actor_id: str = "identity_store",
        audit_metadata: Mapping[str, Any] | None = None,
    ) -> IdentityRecord:
        """Insert one mapping and its audit event in one transaction."""
        mapping = self._coerce_mapping(telegram_user_id, user_id, tenant_id, role, status)
        validate_telegram_user_id(mapping.telegram_user_id)
        with self._transaction():
            prior_rows = self._connection.execute(
                "SELECT tenant_id, role, status FROM identity_mappings WHERE user_id = ?",
                (mapping.user_id,),
            ).fetchall()
            desired_context = (mapping.tenant_id, mapping.role.value, mapping.status.value)
            if any(tuple(row) != desired_context for row in prior_rows):
                raise AmbiguousIdentityMapping(
                    "one user cannot map to incompatible tenant, role, or status contexts"
                )
            try:
                now = _utc_now()
                self._connection.execute(
                    """
                    INSERT INTO identity_mappings (
                        telegram_user_id, user_id, tenant_id, role, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mapping.telegram_user_id,
                        mapping.user_id,
                        mapping.tenant_id,
                        mapping.role.value,
                        mapping.status.value,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if self._fetch_mapping_row(mapping.telegram_user_id) is not None:
                    raise DuplicateIdentityMapping(
                        "duplicate Telegram identity mapping"
                    ) from exc
                raise IdentityStoreError("identity mapping constraint rejected") from exc
            self._append_audit(
                action="mapping.added",
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="identity_mapping",
                telegram_user_id=mapping.telegram_user_id,
                result="success",
                metadata=audit_metadata,
            )
            row = self._fetch_mapping_row(mapping.telegram_user_id)
            if row is None:
                raise IdentityStoreError("mapping disappeared before commit")
            return _row_to_record(row)

    def resolve_mapping(self, telegram_user_id: Any) -> IdentityRecord | None:
        """Resolve an exact literal Telegram ID; invalid and unknown values deny."""
        try:
            literal = validate_telegram_user_id(telegram_user_id)
        except ValueError:
            return None
        self._ensure_open()
        with self._lock:
            row = self._fetch_mapping_row(literal)
            return _row_to_record(row) if row is not None else None

    def set_mapping_status(
        self,
        telegram_user_id: Any,
        status: Any,
        *,
        actor_type: str = "system",
        actor_id: str = "identity_store",
        audit_metadata: Mapping[str, Any] | None = None,
    ) -> IdentityRecord:
        """Change status and audit it atomically; unknown IDs fail closed."""
        try:
            literal = validate_telegram_user_id(telegram_user_id)
            new_status = IdentityStatus(status)
        except (TypeError, ValueError) as exc:
            raise IdentityStoreValidationError("invalid Telegram ID or status") from exc

        with self._transaction():
            row = self._fetch_mapping_row(literal)
            if row is None:
                raise MappingNotFound("unknown Telegram identity mapping")
            sibling_rows = self._connection.execute(
                """
                SELECT tenant_id, role, status
                FROM identity_mappings
                WHERE user_id = ? AND telegram_user_id <> ?
                """,
                (row["user_id"], literal),
            ).fetchall()
            desired_context = (row["tenant_id"], row["role"], new_status.value)
            if any(tuple(sibling) != desired_context for sibling in sibling_rows):
                raise AmbiguousIdentityMapping(
                    "status change would make one user context ambiguous"
                )
            updated_at = _utc_now()
            self._connection.execute(
                """
                UPDATE identity_mappings
                SET status = ?, updated_at = ?
                WHERE telegram_user_id = ?
                """,
                (new_status.value, updated_at, literal),
            )
            self._append_audit(
                action="mapping.status_changed",
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="identity_mapping",
                telegram_user_id=literal,
                result="success",
                metadata=audit_metadata,
            )
            updated = self._fetch_mapping_row(literal)
            if updated is None:
                raise IdentityStoreError("mapping disappeared before commit")
            return _row_to_record(updated)

    def read_audit_events(self, limit: int = 100) -> tuple[AuditEvent, ...]:
        """Read bounded, newest-first audit events without raw identity values."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_AUDIT_EVENTS_READ:
            raise IdentityStoreValidationError(
                f"limit must be an integer from 1 to {MAX_AUDIT_EVENTS_READ}"
            )
        self._ensure_open()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, event_timestamp, action, actor_type, actor_id,
                       target_type, identity_fingerprint, result, metadata_json
                FROM audit_events
                ORDER BY event_timestamp DESC, event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: list[AuditEvent] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise IdentityStoreError("stored audit metadata is invalid JSON") from exc
            if not isinstance(metadata, dict):
                raise IdentityStoreError("stored audit metadata is not an object")
            events.append(
                AuditEvent(
                    event_id=row["event_id"],
                    timestamp=row["event_timestamp"],
                    action=row["action"],
                    actor_type=row["actor_type"],
                    actor_id=row["actor_id"],
                    target_type=row["target_type"],
                    identity_fingerprint=row["identity_fingerprint"],
                    result=row["result"],
                    metadata=metadata,
                )
            )
        return tuple(events)


def initialize_identity_store(path: str | os.PathLike[str]) -> IdentityStore:
    """Open or create a v1 store at the explicitly supplied SQLite path."""
    try:
        database_path = os.fspath(path)
    except TypeError as exc:
        raise IdentityStoreValidationError("database path must be explicitly supplied") from exc
    if not isinstance(database_path, str) or not database_path.strip():
        raise IdentityStoreValidationError("database path must be a non-empty path")
    if database_path != ":memory:" and Path(database_path).is_dir():
        raise IdentityStoreValidationError("database path must name a file, not a directory")
    try:
        connection = sqlite3.connect(
            database_path,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        store = IdentityStore(connection, database_path)
        store._initialize_schema()
        return store
    except Exception:
        try:
            connection.close()
        except (UnboundLocalError, AttributeError):
            pass
        raise


def add_mapping(store: IdentityStore, *args: Any, **kwargs: Any) -> IdentityRecord:
    """Functional wrapper around :meth:`IdentityStore.add_mapping`."""
    if not isinstance(store, IdentityStore):
        raise TypeError("store must be an IdentityStore")
    return store.add_mapping(*args, **kwargs)


def resolve_mapping(store: IdentityStore, telegram_user_id: Any) -> IdentityRecord | None:
    """Functional wrapper around :meth:`IdentityStore.resolve_mapping`."""
    if not isinstance(store, IdentityStore):
        raise TypeError("store must be an IdentityStore")
    return store.resolve_mapping(telegram_user_id)


def set_mapping_status(store: IdentityStore, *args: Any, **kwargs: Any) -> IdentityRecord:
    """Functional wrapper around :meth:`IdentityStore.set_mapping_status`."""
    if not isinstance(store, IdentityStore):
        raise TypeError("store must be an IdentityStore")
    return store.set_mapping_status(*args, **kwargs)


__all__ = [
    "AmbiguousIdentityMapping",
    "AuditEvent",
    "AuditMetadataError",
    "DuplicateIdentityMapping",
    "IdentityRecord",
    "IdentityStore",
    "IdentityStoreError",
    "IdentityStoreValidationError",
    "MappingNotFound",
    "PlatformAdminMappingError",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "add_mapping",
    "initialize_identity_store",
    "resolve_mapping",
    "set_mapping_status",
]
