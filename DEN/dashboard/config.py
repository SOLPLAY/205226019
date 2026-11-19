"""Configuration for the localhost-only monitoring dashboard."""

from __future__ import annotations

import ipaddress
import math
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class MonitoredNode:
    name: str
    endpoint: str
    expected_node_id: str | None


@dataclass(frozen=True)
class DashboardConfig:
    listen_host: str
    listen_port: int
    poll_timeout_seconds: float
    nodes: tuple[MonitoredNode, ...]
    monitor_server_url: str | None
    monitor_api_token_file: Path | None
    monitor_ca_file: Path | None
    tls_ca_file: Path | None
    tls_cert_file: Path | None
    tls_key_file: Path | None


def load_config(path: str | Path) -> DashboardConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load dashboard config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("dashboard configuration must be a YAML mapping")

    host = raw.get("listen_host", "127.0.0.1")
    port = raw.get("listen_port", 8765)
    if not isinstance(host, str) or not host.strip():
        raise ValueError("listen_host must be a non-empty string")
    try:
        is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise ValueError("the monitoring dashboard must bind to a loopback address")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("listen_port must be an integer between 1 and 65535")

    timeout = raw.get("poll_timeout_seconds", 2)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("poll_timeout_seconds must be a positive number")

    monitor_server_url = raw.get("monitor_server_url")
    monitor_api_token_file_raw = raw.get("monitor_api_token_file")
    monitor_ca_file_raw = raw.get("monitor_ca_file")
    monitor_ca_path = None
    if monitor_server_url is not None:
        if not isinstance(monitor_server_url, str) or not monitor_server_url.strip():
            raise ValueError("monitor_server_url must be a non-empty HTTPS URL")
        parsed_monitor = urlsplit(monitor_server_url)
        try:
            monitor_port = parsed_monitor.port
        except ValueError as exc:
            raise ValueError(f"invalid monitor server URL: {monitor_server_url}") from exc
        if (
            parsed_monitor.scheme != "https"
            or parsed_monitor.hostname is None
            or monitor_port is None
            or not 1 <= monitor_port <= 65535
            or parsed_monitor.path not in ("", "/")
            or parsed_monitor.query
            or parsed_monitor.fragment
            or parsed_monitor.username is not None
            or parsed_monitor.password is not None
        ):
            raise ValueError("monitor_server_url must be an HTTPS origin with an explicit port")
        if not isinstance(monitor_api_token_file_raw, str) or not monitor_api_token_file_raw.strip():
            raise ValueError("monitor_api_token_file is required with monitor_server_url")
        raw_nodes = raw.get("nodes", [])
        if not isinstance(raw_nodes, list) or raw_nodes:
            raise ValueError("direct nodes must be omitted when monitor_server_url is configured")
        nodes: list[MonitoredNode] = []
        token_path = Path(monitor_api_token_file_raw).expanduser()
        if not token_path.is_absolute():
            token_path = (config_path.parent / token_path).resolve()
        if not isinstance(monitor_ca_file_raw, str) or not monitor_ca_file_raw.strip():
            raise ValueError("monitor_ca_file is required with monitor_server_url")
        monitor_ca_path = Path(monitor_ca_file_raw).expanduser()
        if not monitor_ca_path.is_absolute():
            monitor_ca_path = (config_path.parent / monitor_ca_path).resolve()
        if not monitor_ca_path.is_file():
            raise ValueError(f"monitor CA certificate does not exist: {monitor_ca_path}")
    else:
        if monitor_api_token_file_raw is not None or monitor_ca_file_raw is not None:
            raise ValueError("monitor API token and CA file require monitor_server_url")
        monitor_ca_path = None
        raw_nodes = raw.get("nodes", [])
        if not isinstance(raw_nodes, list) or not raw_nodes or len(raw_nodes) > 64:
            raise ValueError("nodes must be a list containing between 1 and 64 entries")
        token_path = None
    nodes = []
    seen_endpoints: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, dict):
            raise ValueError("each nodes entry must be a mapping")
        name, endpoint = item.get("name"), item.get("endpoint")
        expected_node_id = item.get("node_id")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("each monitored node must have a non-empty name")
        if not isinstance(endpoint, str):
            raise ValueError(f"node {name} must have an endpoint")
        parsed = urlsplit(endpoint)
        try:
            endpoint_port = parsed.port
        except ValueError as exc:
            raise ValueError(f"invalid endpoint for node {name}: {endpoint}") from exc
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname is None
            or endpoint_port is None
            or not 1 <= endpoint_port <= 65535
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(f"invalid endpoint for node {name}: {endpoint}")
        try:
            endpoint_is_loopback = (
                parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
            )
        except ValueError:
            endpoint_is_loopback = False
        if not endpoint_is_loopback and parsed.scheme != "https":
            raise ValueError(f"non-loopback node {name} must use HTTPS")
        if expected_node_id is not None and (
            not isinstance(expected_node_id, str) or not expected_node_id.strip()
        ):
            raise ValueError(f"node_id for {name} must be a non-empty string when provided")
        if endpoint in seen_endpoints:
            raise ValueError(f"duplicate monitored endpoint: {endpoint}")
        seen_endpoints.add(endpoint)
        nodes.append(
            MonitoredNode(
                name.strip(),
                endpoint.rstrip("/"),
                expected_node_id.strip() if isinstance(expected_node_id, str) else None,
            )
        )

    tls_values = (raw.get("tls_ca_file"), raw.get("tls_cert_file"), raw.get("tls_key_file"))
    if any(value is not None for value in tls_values) and any(
        not isinstance(value, str) or not value.strip() for value in tls_values
    ):
        raise ValueError("tls_ca_file, tls_cert_file, and tls_key_file must be set together")
    if any(node.endpoint.startswith("https://") for node in nodes) and any(value is None for value in tls_values):
        raise ValueError("HTTPS nodes require a dashboard CA file and client certificate/key")
    paths: list[Path] = []
    if all(value is not None for value in tls_values):
        for value in tls_values:
            path_value = Path(value).expanduser()
            if not path_value.is_absolute():
                path_value = (config_path.parent / path_value).resolve()
            if not path_value.is_file():
                raise ValueError(f"TLS file does not exist: {path_value}")
            paths.append(path_value)
        key_mode = stat.S_IMODE(paths[2].stat().st_mode)
        if key_mode & 0o077:
            raise ValueError("tls_key_file must not be accessible by group or other users (use chmod 600)")

    return DashboardConfig(
        host,
        port,
        float(timeout),
        tuple(nodes),
        monitor_server_url.rstrip("/") if monitor_server_url else None,
        token_path,
        monitor_ca_path,
        paths[0] if paths else None,
        paths[1] if paths else None,
        paths[2] if paths else None,
    )
