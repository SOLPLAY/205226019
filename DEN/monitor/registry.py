"""SQLite-backed enrollment and last-seen node registry."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class EnrollmentError(RuntimeError):
    pass


class MonitorRegistry:
    def __init__(
        self,
        database_path: Path,
        enrollment_code: str,
        dashboard_token: str,
        max_enrollments: int,
        suspect_after_seconds: float,
        unavailable_after_seconds: float,
    ) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._enrollment_digest = _digest(enrollment_code)
        self._dashboard_digest = _digest(dashboard_token)
        self._max_enrollments = max_enrollments
        self._suspect_after = suspect_after_seconds
        self._unavailable_after = unavailable_after_seconds
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    node_name TEXT NOT NULL,
                    credential_digest TEXT NOT NULL,
                    enrolled_at REAL NOT NULL,
                    last_seen REAL,
                    uptime_seconds REAL NOT NULL DEFAULT 0,
                    platform TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '',
                    peer_records TEXT NOT NULL DEFAULT '[]'
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def is_dashboard_token(self, token: str) -> bool:
        return hmac.compare_digest(_digest(token), self._dashboard_digest)

    def enroll(self, node_id: str, node_name: str, code: str) -> str:
        if not hmac.compare_digest(_digest(code), self._enrollment_digest):
            raise EnrollmentError("invalid enrollment code")
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            if existing is not None:
                raise EnrollmentError("NodeID is already enrolled; use its saved credential")
            enrolled_count = self._connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            if enrolled_count >= self._max_enrollments:
                raise EnrollmentError("enrollment limit reached")
            token = secrets.token_urlsafe(32)
            self._connection.execute(
                """
                INSERT INTO nodes (node_id, node_name, credential_digest, enrolled_at)
                VALUES (?, ?, ?, ?)
                """,
                (node_id, node_name, _digest(token), time.time()),
            )
            return token

    def heartbeat(self, node_id: str, token: str, report: dict[str, Any]) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT credential_digest, node_name FROM nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            if row is None or not hmac.compare_digest(row["credential_digest"], _digest(token)):
                raise EnrollmentError("unknown node or invalid node credential")
            if row["node_name"] != report["node_name"]:
                raise EnrollmentError("reported node name does not match enrolled identity")
            self._connection.execute(
                """
                UPDATE nodes
                SET last_seen = ?, uptime_seconds = ?, platform = ?, version = ?, peer_records = ?
                WHERE node_id = ?
                """,
                (
                    time.time(),
                    report["uptime_seconds"],
                    report["platform"],
                    report["version"],
                    json.dumps(report["peers"], separators=(",", ":")),
                    node_id,
                ),
            )

    def nodes(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT node_id, node_name, enrolled_at, last_seen, uptime_seconds,
                       platform, version, peer_records
                FROM nodes ORDER BY node_name, node_id
                """
            ).fetchall()
        result = []
        for row in rows:
            last_seen = row["last_seen"]
            age = None if last_seen is None else max(0.0, now - last_seen)
            if age is None or age >= self._unavailable_after:
                status = "UNAVAILABLE"
            elif age >= self._suspect_after:
                status = "SUSPECT"
            else:
                status = "ACTIVE"
            result.append(
                {
                    "node_id": row["node_id"],
                    "node_name": row["node_name"],
                    "name": row["node_name"],
                    "status": status,
                    "state": "ACTIVE" if status == "ACTIVE" else "DEGRADED",
                    "enrolled_at": row["enrolled_at"],
                    "last_seen_at": last_seen,
                    "last_seen_age_seconds": age,
                    "uptime_seconds": row["uptime_seconds"],
                    "platform": row["platform"],
                    "version": row["version"],
                    "peers": json.loads(row["peer_records"]),
                }
            )
        return result


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
