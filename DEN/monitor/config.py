"""Configuration for the node enrollment and monitoring service."""

from __future__ import annotations

import ipaddress
import math
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class MonitorConfig:
    listen_host: str
    listen_port: int
    database_path: Path
    enrollment_code_file: Path
    dashboard_token_file: Path
    tls_cert_file: Path | None
    tls_key_file: Path | None
    tls_ca_file: Path | None
    heartbeat_interval_seconds: float
    suspect_after_seconds: float
    unavailable_after_seconds: float
    max_enrollments: int


def load_config(path: str | Path) -> MonitorConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load monitor config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("monitor configuration must be a YAML mapping")

    host = raw.get("listen_host", "127.0.0.1")
    port = raw.get("listen_port", 8443)
    if not isinstance(host, str) or not host.strip():
        raise ValueError("listen_host must be a non-empty string")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("listen_port must be an integer between 1 and 65535")
    try:
        loopback = ipaddress.ip_address(host).is_loopback or host == "localhost"
    except ValueError:
        loopback = host == "localhost"

    database_path = _path(config_path, raw.get("database_path", "../runtime/monitor.sqlite3"), "database_path")
    enrollment_file = _path(
        config_path, raw.get("enrollment_code_file", "../runtime/enrollment-code"), "enrollment_code_file"
    )
    dashboard_token_file = _path(
        config_path, raw.get("dashboard_token_file", "../runtime/dashboard-token"), "dashboard_token_file"
    )
    cert_value, key_value, ca_value = (
        raw.get("tls_cert_file"),
        raw.get("tls_key_file"),
        raw.get("tls_ca_file"),
    )
    tls_values = (cert_value, key_value, ca_value)
    if any(value is not None for value in tls_values) and any(
        not isinstance(value, str) or not value.strip() for value in tls_values
    ):
        raise ValueError("tls_cert_file, tls_key_file, and tls_ca_file must be set together")
    cert_path = _path(config_path, cert_value, "tls_cert_file") if cert_value is not None else None
    key_path = _path(config_path, key_value, "tls_key_file") if key_value is not None else None
    ca_path = _path(config_path, ca_value, "tls_ca_file") if ca_value is not None else None
    if not loopback and cert_path is None:
        raise ValueError("a non-loopback monitor listener requires TLS certificate and key files")
    if cert_path is not None:
        if not cert_path.is_file() or not key_path.is_file() or not ca_path.is_file():
            raise ValueError("monitor TLS certificate, key, and CA files must exist")
        if stat.S_IMODE(key_path.stat().st_mode) & 0o077:
            raise ValueError("tls_key_file must not be accessible by group or other users (use chmod 600)")

    interval = _positive(raw.get("heartbeat_interval_seconds", 5), "heartbeat_interval_seconds")
    suspect_after = _positive(raw.get("suspect_after_seconds", 12), "suspect_after_seconds")
    unavailable_after = _positive(raw.get("unavailable_after_seconds", 25), "unavailable_after_seconds")
    if suspect_after <= interval or unavailable_after <= suspect_after:
        raise ValueError(
            "heartbeat timing must satisfy heartbeat_interval < suspect_after < unavailable_after"
        )
    max_enrollments = raw.get("max_enrollments", 3)
    if isinstance(max_enrollments, bool) or not isinstance(max_enrollments, int) or max_enrollments < 1:
        raise ValueError("max_enrollments must be a positive integer")

    return MonitorConfig(
        host.strip(),
        port,
        database_path,
        enrollment_file,
        dashboard_token_file,
        cert_path,
        key_path,
        ca_path,
        interval,
        suspect_after,
        unavailable_after,
        max_enrollments,
    )


def _positive(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(value)


def _path(config_path: Path, value: object, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()
