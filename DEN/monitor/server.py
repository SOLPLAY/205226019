"""LAN monitoring server for outbound node enrollment and heartbeat reports."""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import ssl
import stat
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from monitor.config import MonitorConfig, load_config
from monitor.registry import EnrollmentError, MonitorRegistry


def _load_or_create_secret(path: Path, label: str) -> tuple[str, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as secret_file:
            secret = secrets.token_urlsafe(24)
            secret_file.write(f"{secret}\n")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return secret, True
    except FileExistsError:
        secret = path.read_text(encoding="utf-8").strip()
        if not secret:
            raise ValueError(f"{label} file is empty: {path}")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError(f"{label} file must not be accessible by group or other users (use chmod 600)")
        return secret, False


def _report(body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    node_id, node_name = body.get("node_id"), body.get("node_name")
    if not isinstance(node_id, str) or not 1 <= len(node_id) <= 128:
        raise ValueError("node_id must be a string of 1 to 128 characters")
    if not isinstance(node_name, str) or not 1 <= len(node_name) <= 128:
        raise ValueError("node_name must be a string of 1 to 128 characters")
    uptime = body.get("uptime_seconds")
    if (
        isinstance(uptime, bool)
        or not isinstance(uptime, (int, float))
        or not math.isfinite(uptime)
        or uptime < 0
    ):
        raise ValueError("uptime_seconds must be a non-negative number")
    platform, version = body.get("platform"), body.get("version")
    if not isinstance(platform, str) or len(platform) > 256:
        raise ValueError("platform must be a string of at most 256 characters")
    if not isinstance(version, str) or len(version) > 64:
        raise ValueError("version must be a string of at most 64 characters")
    peers = body.get("peers", [])
    if not isinstance(peers, list) or len(peers) > 32:
        raise ValueError("peers must be a list of at most 32 entries")
    if any(not isinstance(peer, dict) for peer in peers):
        raise ValueError("each peer report must be an object")
    return {
        "node_id": node_id,
        "node_name": node_name,
        "uptime_seconds": float(uptime),
        "platform": platform,
        "version": version,
        "peers": peers,
    }


class MonitorServer:
    def __init__(self, config: MonitorConfig, enrollment_code: str, dashboard_token: str) -> None:
        self.config = config
        self.enrollment_code = enrollment_code
        self.registry = MonitorRegistry(
            config.database_path,
            enrollment_code,
            dashboard_token,
            config.max_enrollments,
            config.suspect_after_seconds,
            config.unavailable_after_seconds,
        )
        monitor = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "DENMonitor/0.1"

            def log_message(self, format: str, *args: object) -> None:
                logging.getLogger("den.monitor.http").info(format, *args)

            def _respond(self, status: int, body: dict[str, object]) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(encoded)

            def _body(self) -> dict[str, Any]:
                length_text = self.headers.get("Content-Length", "0")
                if not length_text.isdigit():
                    raise ValueError("invalid content length")
                length = int(length_text)
                if not 1 <= length <= 16384:
                    raise ValueError("request body must be between 1 byte and 16 KiB")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
                return body

            def do_POST(self) -> None:
                try:
                    body = self._body()
                    if self.path == "/api/v1/enroll":
                        node_id, node_name, code = (
                            body.get("node_id"),
                            body.get("node_name"),
                            body.get("enrollment_code"),
                        )
                        if not all(isinstance(value, str) and value for value in (node_id, node_name, code)):
                            self._respond(400, {"error": "node_id, node_name, and enrollment_code are required"})
                            return
                        token = monitor.registry.enroll(node_id, node_name, code)
                        self._respond(201, {"node_id": node_id, "credential": token})
                    elif self.path == "/api/v1/heartbeat":
                        report = _report(body)
                        authorization = self.headers.get("Authorization", "")
                        prefix = "Bearer "
                        if not authorization.startswith(prefix):
                            self._respond(401, {"error": "bearer node credential required"})
                            return
                        monitor.registry.heartbeat(
                            report["node_id"], authorization[len(prefix):], report
                        )
                        self._respond(200, {"accepted": True})
                    else:
                        self._respond(404, {"error": "not found"})
                except EnrollmentError as exc:
                    self._respond(403, {"error": str(exc)})
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    self._respond(400, {"error": str(exc)})

            def do_GET(self) -> None:
                if self.path not in ("/api/v1/nodes", "/api/v1/pairing"):
                    self._respond(404, {"error": "not found"})
                    return
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                if not authorization.startswith(prefix) or not monitor.registry.is_dashboard_token(
                    authorization[len(prefix):]
                ):
                    self._respond(401, {"error": "dashboard bearer token required"})
                    return
                if self.path == "/api/v1/nodes":
                    self._respond(200, {"nodes": monitor.registry.nodes()})
                    return
                if monitor.config.tls_ca_file is None:
                    self._respond(503, {"error": "monitor CA certificate is not configured"})
                    return
                host = self.headers.get("Host", "")
                self._respond(
                    200,
                    {
                        "monitor_url": f"https://{host}",
                        "enrollment_code": monitor.enrollment_code,
                        "ca_certificate_pem": monitor.config.tls_ca_file.read_text(encoding="utf-8"),
                    },
                )

        self.server = ThreadingHTTPServer((config.listen_host, config.listen_port), Handler)
        if config.tls_cert_file is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(config.tls_cert_file), str(config.tls_key_file))
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)

    def serve_forever(self) -> None:
        try:
            self.server.serve_forever()
        finally:
            self.server.server_close()
            self.registry.close()

    def shutdown(self) -> None:
        self.server.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the DEN LAN enrollment and monitoring server.")
    parser.add_argument("--config", required=True, help="path to monitor YAML configuration")
    parser.add_argument("--print-dashboard-token", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        enrollment_code, enrollment_created = _load_or_create_secret(
            config.enrollment_code_file, "enrollment code"
        )
        dashboard_token, dashboard_created = _load_or_create_secret(
            config.dashboard_token_file, "dashboard token"
        )
        if enrollment_created:
            print(f"One-time enrollment code (share only with your devices): {enrollment_code}", flush=True)
        if dashboard_created or args.print_dashboard_token:
            print(f"Dashboard API token (keep private): {dashboard_token}", flush=True)
        server = MonitorServer(config, enrollment_code, dashboard_token)
        scheme = "https" if config.tls_cert_file else "http"
        logging.info("DEN monitor listening at %s://%s:%s", scheme, config.listen_host, config.listen_port)
        server.serve_forever()
    except (OSError, ValueError) as exc:
        logging.error("monitor server could not start: %s", exc)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
