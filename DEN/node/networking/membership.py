"""Thread-safe local peer registry and heartbeat health transitions."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class PeerState(StrEnum):
    ALIVE = "ALIVE"
    SUSPECT = "SUSPECT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class PeerRecord:
    node_id: str
    node_name: str
    host: str
    port: int
    scheme: str = "http"
    state: PeerState = PeerState.ALIVE
    missed_heartbeats: int = 0
    last_seen_monotonic: float = 0.0
    last_seen_at: str = ""

    def as_status(self) -> dict[str, object]:
        age = None if not self.last_seen_monotonic else max(0.0, time.monotonic() - self.last_seen_monotonic)
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "endpoint": f"{self.scheme}://{self.host}:{self.port}",
            "state": self.state.value,
            "missed_heartbeats": self.missed_heartbeats,
            "last_seen_at": self.last_seen_at or None,
            "last_seen_age_seconds": age,
        }


class PeerRegistry:
    def __init__(self) -> None:
        self._records: dict[str, PeerRecord] = {}
        self._lock = threading.RLock()

    def upsert(self, node_id: str, node_name: str, host: str, port: int, scheme: str = "http") -> PeerRecord:
        now = time.monotonic()
        with self._lock:
            record = self._records.get(node_id)
            if record is None:
                record = PeerRecord(node_id, node_name, host, port, scheme)
                self._records[node_id] = record
            record.node_name = node_name
            record.host = host
            record.port = port
            record.scheme = scheme
            self._mark_alive(record, now)
            return record

    def learn(self, node_id: str, node_name: str, host: str, port: int, scheme: str = "http") -> PeerRecord:
        with self._lock:
            record = self._records.get(node_id)
            if record is None:
                record = PeerRecord(
                    node_id,
                    node_name,
                    host,
                    port,
                    scheme=scheme,
                    state=PeerState.SUSPECT,
                )
                self._records[node_id] = record
            else:
                record.node_name = node_name
                record.host = host
                record.port = port
                record.scheme = scheme
            return record

    def mark_alive(self, node_id: str) -> PeerRecord:
        with self._lock:
            record = self._records[node_id]
            self._mark_alive(record, time.monotonic())
            return record

    @staticmethod
    def _mark_alive(record: PeerRecord, now: float) -> None:
        record.state = PeerState.ALIVE
        record.missed_heartbeats = 0
        record.last_seen_monotonic = now
        record.last_seen_at = datetime.now(timezone.utc).isoformat()

    def mark_missed(self, node_id: str, unavailable_after: int) -> PeerRecord:
        with self._lock:
            record = self._records[node_id]
            record.missed_heartbeats += 1
            record.state = (
                PeerState.UNAVAILABLE
                if record.missed_heartbeats >= unavailable_after
                else PeerState.SUSPECT
            )
            return record

    def get(self, node_id: str) -> PeerRecord | None:
        with self._lock:
            return self._records.get(node_id)

    def list(self) -> list[PeerRecord]:
        with self._lock:
            return list(self._records.values())

    def summaries(self, limit: int = 32) -> list[dict[str, object]]:
        return [
            {
                "node_id": record.node_id,
                "node_name": record.node_name,
                "host": record.host,
                "port": record.port,
                "scheme": record.scheme,
                "state": record.state.value,
            }
            for record in self.list()[:limit]
        ]

    def statuses(self) -> list[dict[str, object]]:
        return [record.as_status() for record in self.list()]