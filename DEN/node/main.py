"""Command-line entry point and local HTTP API for a DEN node."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import ssl
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from node.config import NodeConfig, load_config, load_data_dir
from node.identity import NodeIdentity
from node.lifecycle import LifecycleState
from node.networking.discovery import PeerDiscovery
from node.networking.heartbeat import HeartbeatMonitor
from node.networking.membership import PeerRegistry
from node.networking.transport import HttpTransport
from protocols.messages import (
    PROTOCOL_VERSION,
    HeartbeatRequest,
    HeartbeatResponse,
    HelloRequest,
    HelloResponse,
    PeerSummary,
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "node_id": getattr(record, "node_id", "-"),
            "component": record.name,
            "message": record.getMessage(),
        }
        for key in ("endpoint", "peer_node_id", "from_state", "to_state", "error"):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        return json.dumps(event, ensure_ascii=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


class NodeApplication:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.identity: NodeIdentity | None = None
        self.registry = PeerRegistry()
        self.lifecycle = LifecycleState.INITIALIZING
        self.started_at = time.monotonic()
        self.server: ThreadingHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self._stop_event = asyncio.Event()
        self.logger = logging.getLogger("den.node")

    async def run(self) -> None:
        self.identity = NodeIdentity.open(self.config.data_dir)
        try:
            transport = HttpTransport(
                self.config.heartbeat_timeout_seconds,
                self.config.tls_ca_file,
                self.config.tls_cert_file,
                self.config.tls_key_file,
            )
            discovery = PeerDiscovery(self.config, self.identity.node_id, self.registry, transport)
            heartbeat = HeartbeatMonitor(self.config, self.identity.node_id, self.registry, transport, discovery)
            self.server = self._make_server()
            self.server_thread = threading.Thread(target=self.server.serve_forever, name="den-http", daemon=True)
            self.server_thread.start()
            self.lifecycle = LifecycleState.ACTIVE
            self.logger.info(
                "node started",
                extra={"node_id": self.identity.node_id},
            )
            tasks = [asyncio.create_task(discovery.run()), asyncio.create_task(heartbeat.run())]
            stop_task = asyncio.create_task(self._stop_event.wait())
            try:
                done, _ = await asyncio.wait(
                    [*tasks, stop_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task not in done:
                    for task in done:
                        task.result()
                    raise RuntimeError("background node task stopped unexpectedly")
            finally:
                self.lifecycle = LifecycleState.STOPPING
                stop_task.cancel()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.gather(stop_task, return_exceptions=True)
                for task in tasks:
                    if not task.cancelled() and task.exception() is not None:
                        self.logger.error(
                            "background node task failed",
                            extra={"node_id": self.identity.node_id, "error": str(task.exception())},
                        )
        finally:
            if self.server is not None:
                await asyncio.to_thread(self.server.shutdown)
                self.server.server_close()
            if self.server_thread is not None:
                self.server_thread.join(timeout=2)
            self.logger.info("node stopped", extra={"node_id": self.identity.node_id})
            self.identity.close()

    def request_stop(self) -> None:
        self._stop_event.set()

    def _make_server(self) -> ThreadingHTTPServer:
        application = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                logging.getLogger("den.http").debug(
                    format,
                    *args,
                    extra={"node_id": application.identity.node_id if application.identity else "-"},
                )

            def _respond(self, status: int, body: dict[str, object]) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:
                if not self._authorized_dashboard_or_peer():
                    self._respond(403, {"error": "client certificate identity is not trusted"})
                    return
                if self.path == "/status":
                    self._respond(
                        200,
                        {
                            "node_id": application.identity.node_id if application.identity else None,
                            "node_name": application.config.node_name,
                            "state": application.lifecycle.value,
                            "listen_host": application.config.listen_host,
                            "advertised_host": application.config.advertised_host,
                            "listen_port": application.config.listen_port,
                            "uptime_seconds": max(0.0, time.monotonic() - application.started_at),
                        },
                    )
                elif self.path == "/peers":
                    self._respond(200, {"peers": application.registry.statuses()})
                else:
                    self._respond(404, {"error": "not found"})

            def do_POST(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 65536:
                        raise ValueError("request body must be between 1 byte and 64 KiB")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("request body must be a JSON object")
                    if self.path == "/hello":
                        self._hello(body)
                    elif self.path == "/heartbeat":
                        self._heartbeat(body)
                    else:
                        self._respond(404, {"error": "not found"})
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    self._respond(400, {"error": str(exc)})

            def _trusted(self, node_id: str) -> bool:
                certificate_id = self._client_certificate_id()
                certificate_matches = (
                    certificate_id == node_id
                    if application.config.tls_cert_file is not None
                    else True
                )
                trusted = (
                    certificate_matches
                    and (
                        "*" in application.config.trusted_peer_ids
                        or node_id in application.config.trusted_peer_ids
                    )
                )
                if not trusted:
                    logging.getLogger("den.http").warning(
                        "rejected untrusted peer identity",
                        extra={"node_id": application.identity.node_id, "peer_node_id": node_id},
                    )
                return trusted

            def _client_certificate_id(self) -> str | None:
                if application.config.tls_cert_file is None:
                    return None
                certificate = self.connection.getpeercert()
                common_names = []
                for rdn in certificate.get("subject", ()):
                    for key, value in rdn:
                        if key == "commonName":
                            common_names.append(value)
                return common_names[0] if len(common_names) == 1 else None

            def _authorized_dashboard_or_peer(self) -> bool:
                if application.config.tls_cert_file is None:
                    return True
                client_id = self._client_certificate_id()
                return client_id in (
                    *application.config.trusted_peer_ids,
                    *application.config.trusted_dashboard_ids,
                )

            def _hello(self, body: dict[str, Any]) -> None:
                request = HelloRequest.from_dict(body)
                if application.config.tls_cert_file is not None and request.advertised_scheme != "https":
                    self._respond(400, {"error": "mutual TLS peers must advertise an HTTPS endpoint"})
                    return
                if request.node_id == application.identity.node_id:
                    self._respond(400, {"error": "a node cannot introduce itself as a peer"})
                    return
                if not self._trusted(request.node_id):
                    self._respond(403, {"error": "peer identity is not trusted"})
                    return
                application.registry.upsert(
                    request.node_id,
                    request.node_name,
                    request.advertised_host,
                    request.advertised_port,
                    request.advertised_scheme,
                )
                response = HelloResponse(
                    PROTOCOL_VERSION,
                    application.identity.node_id,
                    application.config.node_name,
                    True,
                    ("hello", "heartbeat"),
                    tuple(
                        PeerSummary(
                            peer["node_id"], peer["node_name"], peer["host"], peer["port"],
                            peer["scheme"], peer["state"]
                        )
                        for peer in application.registry.summaries()
                    ),
                )
                self._respond(200, response.to_dict())

            def _heartbeat(self, body: dict[str, Any]) -> None:
                request = HeartbeatRequest.from_dict(body)
                if not self._trusted(request.sender_node_id):
                    self._respond(403, {"error": "peer identity is not trusted"})
                    return
                response = HeartbeatResponse(
                    PROTOCOL_VERSION,
                    application.identity.node_id,
                    request.sequence,
                    datetime.now(timezone.utc).isoformat(),
                )
                self._respond(200, response.to_dict())

        server = ThreadingHTTPServer(
            (self.config.listen_host, self.config.listen_port),
            Handler,
        )
        if self.config.tls_cert_file is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(
                certfile=str(self.config.tls_cert_file),
                keyfile=str(self.config.tls_key_file),
            )
            context.load_verify_locations(cafile=str(self.config.tls_ca_file))
            context.verify_mode = ssl.CERT_REQUIRED
            server.socket = context.wrap_socket(server.socket, server_side=True)
        return server


async def _serve(config: NodeConfig) -> None:
    app = NodeApplication(config)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, app.request_stop)
    await app.run()


def _status(config: NodeConfig) -> int:
    endpoint = config.advertised_endpoint
    transport = HttpTransport(
        config.heartbeat_timeout_seconds,
        config.tls_ca_file,
        config.tls_cert_file,
        config.tls_key_file,
    )
    status = transport.get_json(endpoint, "/status")
    node_id = status.get("node_id")
    print(json.dumps(status, indent=2))
    print(json.dumps(transport.get_json(endpoint, "/peers", expected_peer_id=node_id), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or inspect a DEN node.")
    parser.add_argument("--config", required=True, help="path to the node YAML configuration")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="print status and known peers")
    mode.add_argument("--init-identity", action="store_true", help="create or print the persistent NodeID")
    args = parser.parse_args()
    try:
        if args.init_identity:
            identity = NodeIdentity.open(load_data_dir(args.config))
            try:
                print(identity.node_id)
            finally:
                identity.close()
            return 0
        config = load_config(args.config)
        if args.status:
            return _status(config)
        configure_logging()
        asyncio.run(_serve(config))
    except (OSError, RuntimeError, ValueError) as exc:
        logging.getLogger("den.node").error("node could not start: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())