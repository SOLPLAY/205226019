"""Node configuration loading and validation."""

from __future__ import annotations

import ipaddress
import math
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class NodeConfig:
    node_name: str
    data_dir: Path
    listen_host: str
    advertised_host: str
    listen_port: int
    bootstrap_peers: tuple[str, ...]
    trusted_peer_ids: tuple[str, ...]
    trusted_dashboard_ids: tuple[str, ...]
    tls_ca_file: Path | None
    tls_cert_file: Path | None
    tls_key_file: Path | None
    heartbeat_interval_seconds: float
    heartbeat_timeout_seconds: float
    unavailable_after_misses: int

    @property
    def endpoint(self) -> str:
        host = f"[{self.listen_host}]" if ":" in self.listen_host else self.listen_host
        scheme = "https" if self.tls_cert_file is not None else "http"
        return f"{scheme}://{host}:{self.listen_port}"

    @property
    def advertised_endpoint(self) -> str:
        host = f"[{self.advertised_host}]" if ":" in self.advertised_host else self.advertised_host
        scheme = "https" if self.tls_cert_file is not None else "http"
        return f"{scheme}://{host}:{self.listen_port}"


def load_config(path: str | Path) -> NodeConfig:
    config_path = Path(path).expanduser().resolve()
    raw = _read_config(config_path)

    if not isinstance(raw, dict):
        raise ValueError("configuration must be a YAML mapping")

    required = ("node_name", "data_dir", "listen_host", "listen_port")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"missing configuration fields: {', '.join(missing)}")

    node_name = raw["node_name"]
    listen_host = raw["listen_host"]
    advertised_host = raw.get("advertised_host", listen_host)
    listen_port = raw["listen_port"]
    data_dir_raw = raw["data_dir"]
    if not isinstance(node_name, str) or not node_name.strip():
        raise ValueError("node_name must be a non-empty string")
    if not isinstance(listen_host, str) or not listen_host.strip():
        raise ValueError("listen_host must be a non-empty string")
    if not isinstance(advertised_host, str) or not advertised_host.strip():
        raise ValueError("advertised_host must be a non-empty string")
    try:
        advertised_is_unspecified = ipaddress.ip_address(advertised_host).is_unspecified
    except ValueError:
        advertised_is_unspecified = False
    if advertised_is_unspecified:
        raise ValueError("advertised_host must be a reachable address, not a wildcard bind address")
    if isinstance(listen_port, bool) or not isinstance(listen_port, int) or not 1 <= listen_port <= 65535:
        raise ValueError("listen_port must be an integer between 1 and 65535")
    if not isinstance(data_dir_raw, str) or not data_dir_raw.strip():
        raise ValueError("data_dir must be a non-empty path")

    data_dir = resolve_data_dir(config_path, data_dir_raw)

    bootstrap_peers = _string_list(raw.get("bootstrap_peers", []), "bootstrap_peers")
    for peer in bootstrap_peers:
        parsed = urlsplit(peer)
        try:
            peer_port = parsed.port
        except ValueError as exc:
            raise ValueError(f"invalid bootstrap peer endpoint: {peer}") from exc
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or peer_port is None
            or not 1 <= peer_port <= 65535
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"invalid bootstrap peer endpoint: {peer}")

    trusted_peer_ids = _string_list(raw.get("trusted_peer_ids", []), "trusted_peer_ids")
    trusted_dashboard_ids = _string_list(
        raw.get("trusted_dashboard_ids", ["den-dashboard"]), "trusted_dashboard_ids"
    )

    tls_values = (raw.get("tls_ca_file"), raw.get("tls_cert_file"), raw.get("tls_key_file"))
    if any(value is not None for value in tls_values) and any(
        not isinstance(value, str) or not value.strip() for value in tls_values
    ):
        raise ValueError("tls_ca_file, tls_cert_file, and tls_key_file must be set together")
    tls_paths: tuple[Path | None, Path | None, Path | None]
    if all(value is None for value in tls_values):
        tls_paths = (None, None, None)
    else:
        resolved_paths = []
        for value in tls_values:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = (config_path.parent / path).resolve()
            if not path.is_file():
                raise ValueError(f"TLS file does not exist: {path}")
            resolved_paths.append(path)
        key_mode = stat.S_IMODE(resolved_paths[2].stat().st_mode)
        if key_mode & 0o077:
            raise ValueError("tls_key_file must not be accessible by group or other users (use chmod 600)")
        tls_paths = (resolved_paths[0], resolved_paths[1], resolved_paths[2])

    try:
        bind_is_loopback = listen_host == "localhost" or ipaddress.ip_address(listen_host).is_loopback
    except ValueError:
        bind_is_loopback = False
    try:
        advertised_is_loopback = (
            advertised_host == "localhost" or ipaddress.ip_address(advertised_host).is_loopback
        )
    except ValueError:
        advertised_is_loopback = False
    if "*" in trusted_peer_ids and (trusted_peer_ids != ["*"] or not bind_is_loopback):
        raise ValueError("wildcard peer trust is allowed only by itself on a loopback listener")
    if not bind_is_loopback and tls_paths[0] is None:
        raise ValueError("non-loopback listeners require mutual TLS certificate and CA files")
    if not advertised_is_loopback and tls_paths[0] is None:
        raise ValueError("non-loopback advertised hosts require mutual TLS certificate and CA files")
    for peer in bootstrap_peers:
        peer_host = urlsplit(peer).hostname
        try:
            peer_is_loopback = (
                peer_host == "localhost" or ipaddress.ip_address(peer_host).is_loopback
            )
        except ValueError:
            peer_is_loopback = False
        if not peer_is_loopback and urlsplit(peer).scheme != "https":
            raise ValueError("non-loopback bootstrap peers must use HTTPS")
    if tls_paths[0] is not None:
        if "*" in trusted_peer_ids:
            raise ValueError("wildcard trusted_peer_ids cannot be used with mutual TLS")
        if not trusted_peer_ids:
            raise ValueError("mutual TLS requires an explicit trusted_peer_ids allowlist")
        if any(urlsplit(peer).scheme != "https" for peer in bootstrap_peers):
            raise ValueError("mutual TLS nodes may only use https bootstrap peers")
    elif any(urlsplit(peer).scheme == "https" for peer in bootstrap_peers):
        raise ValueError("HTTPS bootstrap peers require configured mutual TLS certificates")

    heartbeat_interval = _positive_number(
        raw.get("heartbeat_interval_seconds", 2), "heartbeat_interval_seconds"
    )
    heartbeat_timeout = _positive_number(
        raw.get("heartbeat_timeout_seconds", 1), "heartbeat_timeout_seconds"
    )
    unavailable_after = raw.get("unavailable_after_misses", 3)
    if isinstance(unavailable_after, bool) or not isinstance(unavailable_after, int) or unavailable_after < 2:
        raise ValueError("unavailable_after_misses must be an integer of at least 2")
    if heartbeat_timeout >= heartbeat_interval:
        raise ValueError("heartbeat_timeout_seconds must be less than heartbeat_interval_seconds")

    return NodeConfig(
        node_name=node_name.strip(),
        data_dir=data_dir,
        listen_host=listen_host.strip(),
        advertised_host=advertised_host.strip(),
        listen_port=listen_port,
        bootstrap_peers=tuple(dict.fromkeys(peer.rstrip("/") for peer in bootstrap_peers)),
        trusted_peer_ids=tuple(trusted_peer_ids),
        trusted_dashboard_ids=tuple(trusted_dashboard_ids),
        tls_ca_file=tls_paths[0],
        tls_cert_file=tls_paths[1],
        tls_key_file=tls_paths[2],
        heartbeat_interval_seconds=heartbeat_interval,
        heartbeat_timeout_seconds=heartbeat_timeout,
        unavailable_after_misses=unavailable_after,
    )


def load_data_dir(path: str | Path) -> Path:
    config_path = Path(path).expanduser().resolve()
    raw = _read_config(config_path)
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a YAML mapping")
    data_dir_raw = raw.get("data_dir")
    if not isinstance(data_dir_raw, str) or not data_dir_raw.strip():
        raise ValueError("data_dir must be a non-empty path")
    return resolve_data_dir(config_path, data_dir_raw)


def _read_config(config_path: Path) -> object:
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load config {config_path}: {exc}") from exc


def resolve_data_dir(config_path: Path, data_dir_raw: str) -> Path:
    data_dir = Path(data_dir_raw).expanduser()
    if not data_dir.is_absolute():
        data_dir = (config_path.parent / data_dir).resolve()
    return data_dir


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _positive_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a positive number")
    return float(value)