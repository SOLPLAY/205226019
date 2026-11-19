"""Typed, versioned JSON message contracts used by DEN nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PROTOCOL_VERSION = 1


def _required(data: dict[str, Any], key: str, expected: type) -> Any:
    value = data.get(key)
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        raise ValueError(f"{key} must be {expected.__name__}")
    return value


def _protocol(data: dict[str, Any]) -> int:
    version = _required(data, "protocol_version", int)
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol_version: {version}")
    return version


@dataclass(frozen=True)
class PeerSummary:
    node_id: str
    node_name: str
    host: str
    port: int
    scheme: str
    state: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeerSummary:
        if not isinstance(data, dict):
            raise ValueError("each known peer must be a JSON object")
        _required(data, "node_id", str)
        _required(data, "node_name", str)
        _required(data, "host", str)
        port = _required(data, "port", int)
        scheme = _required(data, "scheme", str)
        _required(data, "state", str)
        if not 1 <= port <= 65535:
            raise ValueError("peer port must be between 1 and 65535")
        if scheme not in ("http", "https"):
            raise ValueError("peer scheme must be http or https")
        return cls(
            data["node_id"], data["node_name"], data["host"], port, scheme, data["state"]
        )


@dataclass(frozen=True)
class HelloRequest:
    protocol_version: int
    node_id: str
    node_name: str
    advertised_host: str
    advertised_port: int
    advertised_scheme: str = "http"
    capabilities: tuple[str, ...] = ("hello", "heartbeat")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HelloRequest:
        version = _protocol(data)
        for key in ("node_id", "node_name", "advertised_host"):
            _required(data, key, str)
        port = _required(data, "advertised_port", int)
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
            raise ValueError("capabilities must be a list of strings")
        if not 1 <= port <= 65535:
            raise ValueError("advertised_port must be between 1 and 65535")
        scheme = data.get("advertised_scheme", "http")
        if not isinstance(scheme, str) or scheme not in ("http", "https"):
            raise ValueError("advertised_scheme must be http or https")
        return cls(
            version, data["node_id"], data["node_name"], data["advertised_host"], port,
            scheme, tuple(capabilities)
        )


@dataclass(frozen=True)
class HelloResponse:
    protocol_version: int
    node_id: str
    node_name: str
    accepted: bool
    capabilities: tuple[str, ...]
    known_peers: tuple[PeerSummary, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "accepted": self.accepted,
            "capabilities": list(self.capabilities),
            "known_peers": [asdict(peer) for peer in self.known_peers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HelloResponse:
        version = _protocol(data)
        _required(data, "node_id", str)
        _required(data, "node_name", str)
        accepted = _required(data, "accepted", bool)
        capabilities = data.get("capabilities", [])
        peers = data.get("known_peers", [])
        if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
            raise ValueError("capabilities must be a list of strings")
        if not isinstance(peers, list) or len(peers) > 32:
            raise ValueError("known_peers must be a list of at most 32 entries")
        return cls(
            version,
            data["node_id"],
            data["node_name"],
            accepted,
            tuple(capabilities),
            tuple(PeerSummary.from_dict(peer) for peer in peers),
        )


@dataclass(frozen=True)
class HeartbeatRequest:
    protocol_version: int
    sender_node_id: str
    sequence: int
    sent_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatRequest:
        version = _protocol(data)
        _required(data, "sender_node_id", str)
        _required(data, "sent_at", str)
        sequence = _required(data, "sequence", int)
        if sequence < 0:
            raise ValueError("sequence must be non-negative")
        return cls(version, data["sender_node_id"], sequence, data["sent_at"])


@dataclass(frozen=True)
class HeartbeatResponse:
    protocol_version: int
    responder_node_id: str
    echoed_sequence: int
    received_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatResponse:
        version = _protocol(data)
        _required(data, "responder_node_id", str)
        _required(data, "received_at", str)
        sequence = _required(data, "echoed_sequence", int)
        if sequence < 0:
            raise ValueError("echoed_sequence must be non-negative")
        return cls(version, data["responder_node_id"], sequence, data["received_at"])