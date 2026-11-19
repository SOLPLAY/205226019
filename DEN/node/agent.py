"""Portable foreground node agent that reports through outbound HTTPS."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import platform
import signal
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from monitor.client import MonitorClient, MonitorRequestError
from node.identity import NodeIdentity


@dataclass(frozen=True)
class AgentConfig:
    node_name: str
    data_dir: Path
    monitor_url: str
    monitor_ca_file: Path
    heartbeat_interval_seconds: float
    protocol_version: str


class NodeAgent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._running = True
        self._started_at = time.monotonic()
        self._identity: NodeIdentity | None = None
        self._credential_path = config.data_dir / "monitor-credential.json"
        self._client = MonitorClient(config.monitor_url, config.monitor_ca_file)

    def stop(self, _signum: int | None = None, _frame: object | None = None) -> None:
        self._running = False

    def run(self, enrollment_code: str | None = None) -> None:
        self._identity = NodeIdentity.open(self.config.data_dir)
        try:
            credential = self._load_credential()
            if credential is None:
                code = enrollment_code or getpass.getpass("Enter the one-time DEN enrollment code: ")
                credential = self._enroll(code)
                self._save_credential(credential)
            logging.info("node enrolled as %s (%s)", self.config.node_name, self._identity.node_id)
            while self._running:
                report = {
                    "node_id": self._identity.node_id,
                    "node_name": self.config.node_name,
                    "uptime_seconds": max(0.0, time.monotonic() - self._started_at),
                    "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
                    "version": self.config.protocol_version,
                    "peers": [],
                }
                try:
                    self._client.post(
                        "/api/v1/heartbeat",
                        report,
                        bearer_token=credential["credential"],
                    )
                    logging.info("heartbeat accepted by monitor")
                except MonitorRequestError as exc:
                    logging.warning("heartbeat not delivered: %s", exc)
                self._sleep(self.config.heartbeat_interval_seconds)
        finally:
            self._identity.close()

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(min(0.25, deadline - time.monotonic()))

    def _load_credential(self) -> dict[str, str] | None:
        if not self._credential_path.exists():
            return None
        if os.name != "nt" and stat.S_IMODE(self._credential_path.stat().st_mode) & 0o077:
            raise PermissionError(f"monitor credential file must be private: {self._credential_path}")
        try:
            data = json.loads(self._credential_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read node credential {self._credential_path}: {exc}") from exc
        if (
            not isinstance(data, dict)
            or data.get("node_id") != self._identity.node_id
            or not isinstance(data.get("credential"), str)
        ):
            raise ValueError("saved monitor credential is invalid or belongs to a different NodeID")
        return {"node_id": data["node_id"], "credential": data["credential"]}

    def _enroll(self, code: str) -> dict[str, str]:
        if not code.strip():
            raise ValueError("enrollment code cannot be empty")
        response = self._client.post(
            "/api/v1/enroll",
            {
                "node_id": self._identity.node_id,
                "node_name": self.config.node_name,
                "enrollment_code": code.strip(),
            },
        )
        credential = response.get("credential")
        if response.get("node_id") != self._identity.node_id or not isinstance(credential, str):
            raise MonitorRequestError("monitor returned an invalid enrollment credential")
        return {"node_id": self._identity.node_id, "credential": credential}

    def _save_credential(self, credential: dict[str, str]) -> None:
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".monitor-credential-", dir=self.config.data_dir
        )
        try:
            if os.name != "nt":
                os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(credential, file)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self._credential_path)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            Path(temporary_name).unlink(missing_ok=True)
            raise


def load_config(path: str | Path) -> AgentConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load agent config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("agent configuration must be a YAML mapping")
    node_name = raw.get("node_name")
    monitor_url = raw.get("monitor_url")
    data_dir_raw = raw.get("data_dir")
    ca_file_raw = raw.get("monitor_ca_file")
    interval = raw.get("heartbeat_interval_seconds", 5)
    if not isinstance(node_name, str) or not node_name.strip():
        raise ValueError("node_name must be a non-empty string")
    if not isinstance(monitor_url, str) or not monitor_url.strip():
        raise ValueError("monitor_url must be an HTTPS URL")
    if not isinstance(data_dir_raw, str) or not data_dir_raw.strip():
        raise ValueError("data_dir must be a non-empty path")
    if not isinstance(ca_file_raw, str) or not ca_file_raw.strip():
        raise ValueError("monitor_ca_file must be a non-empty path")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0.1 <= interval <= 300:
        raise ValueError("heartbeat_interval_seconds must be between 0.1 and 300")
    data_dir = Path(data_dir_raw).expanduser()
    ca_file = Path(ca_file_raw).expanduser()
    if not data_dir.is_absolute():
        data_dir = (config_path.parent / data_dir).resolve()
    if not ca_file.is_absolute():
        ca_file = (config_path.parent / ca_file).resolve()
    if not ca_file.is_file():
        raise ValueError(f"monitor CA certificate does not exist: {ca_file}")
    return AgentConfig(
        node_name.strip(),
        data_dir,
        monitor_url.rstrip("/"),
        ca_file,
        float(interval),
        str(raw.get("protocol_version", "0.1")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a DEN node reporting agent.")
    parser.add_argument("--config", required=True, help="path to the portable node-agent YAML config")
    parser.add_argument(
        "--enrollment-code",
        help="one-time enrollment code; omit to enter it without echoing",
    )
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        agent = NodeAgent(config)
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, agent.stop)
        agent.run(args.enrollment_code)
    except (OSError, PermissionError, RuntimeError, ValueError, MonitorRequestError) as exc:
        logging.error("node agent stopped: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
