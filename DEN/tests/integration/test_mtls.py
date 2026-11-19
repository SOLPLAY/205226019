from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from dashboard.config import DashboardConfig, MonitoredNode
from dashboard.main import Dashboard
from node.identity import NodeIdentity
from node.networking.transport import HttpTransport, PeerRequestError
from protocols.messages import HelloRequest, PROTOCOL_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MutualTlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("openssl") is None:
            raise unittest.SkipTest("OpenSSL is required for the mutual-TLS integration test")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server_id = self._generate_node_id("node-data")
        self.client_id = self._generate_node_id("peer-data")
        self.other_id = str(uuid.uuid4())
        self.port = _free_port()
        self.peer_port = _free_port()
        self.processes: list[subprocess.Popen[bytes]] = []
        self.log_path = self.root / "node.log"
        self.log = self.log_path.open("wb")
        self.ca_cert = self.root / "ca.crt"
        self._create_ca()
        self.server_cert, self.server_key = self._create_certificate("server", self.server_id)
        self.client_cert, self.client_key = self._create_certificate("client", self.client_id)
        self.other_cert, self.other_key = self._create_certificate("other", self.other_id)
        self.dashboard_cert, self.dashboard_key = self._create_certificate("dashboard", "den-dashboard")

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        self.log.close()
        self.temporary.cleanup()

    def _run_openssl(self, *args: str) -> None:
        subprocess.run(["openssl", *args], check=True, capture_output=True, text=True)

    def _generate_node_id(self, data_dir: str) -> str:
        identity = NodeIdentity.open(self.root / data_dir)
        node_id = identity.node_id
        identity.close()
        return node_id

    def _create_ca(self) -> None:
        self._run_openssl(
            "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(self.root / "ca.key"),
            "-out", str(self.ca_cert),
            "-subj", "/CN=DEN-Test-CA",
            "-days", "2",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        )

    def _create_certificate(self, name: str, common_name: str) -> tuple[Path, Path]:
        key = self.root / f"{name}.key"
        csr = self.root / f"{name}.csr"
        cert = self.root / f"{name}.crt"
        extensions = self.root / f"{name}.ext"
        arguments = [
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key),
            "-out", str(csr),
            "-subj", f"/CN={common_name}",
        ]
        if name in ("server", "client"):
            arguments.extend(["-addext", "subjectAltName=IP:127.0.0.1"])
        self._run_openssl(*arguments)
        extensions.write_text(
            "basicConstraints=CA:FALSE\n"
            "keyUsage=digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth,clientAuth\n"
            + ("subjectAltName=IP:127.0.0.1\n" if name in ("server", "client") else ""),
            encoding="utf-8",
        )
        key.chmod(0o600)
        self._run_openssl(
            "x509", "-req", "-in", str(csr),
            "-CA", str(self.ca_cert), "-CAkey", str(self.root / "ca.key"),
            "-CAcreateserial", "-out", str(cert), "-days", "2", "-sha256",
            "-extfile", str(extensions),
        )
        return cert, key

    def _write_config(self) -> Path:
        config_path = self.root / "node.yaml"
        config_path.write_text(
            "node_name: secure-node\n"
            f"data_dir: {self.root / 'node-data'}\n"
            "listen_host: 127.0.0.1\n"
            "advertised_host: 127.0.0.1\n"
            f"listen_port: {self.port}\n"
            f"bootstrap_peers: [https://127.0.0.1:{self.peer_port}]\n"
            f"trusted_peer_ids: [{self.client_id!r}]\n"
            f"tls_ca_file: {self.ca_cert}\n"
            f"tls_cert_file: {self.server_cert}\n"
            f"tls_key_file: {self.server_key}\n"
            "heartbeat_interval_seconds: 1\n"
            "heartbeat_timeout_seconds: 0.5\n"
            "unavailable_after_misses: 3\n",
            encoding="utf-8",
        )
        return config_path

    def _write_peer_config(self) -> Path:
        config_path = self.root / "peer.yaml"
        config_path.write_text(
            "node_name: peer-node\n"
            f"data_dir: {self.root / 'peer-data'}\n"
            "listen_host: 127.0.0.1\n"
            "advertised_host: 127.0.0.1\n"
            f"listen_port: {self.peer_port}\n"
            "bootstrap_peers: []\n"
            f"trusted_peer_ids: [{self.server_id!r}]\n"
            f"tls_ca_file: {self.ca_cert}\n"
            f"tls_cert_file: {self.client_cert}\n"
            f"tls_key_file: {self.client_key}\n"
            "heartbeat_interval_seconds: 0.3\n"
            "heartbeat_timeout_seconds: 0.2\n"
            "unavailable_after_misses: 3\n",
            encoding="utf-8",
        )
        return config_path

    def _transport(self, cert: Path, key: Path) -> HttpTransport:
        return HttpTransport(1, self.ca_cert, cert, key)

    def _start_and_wait(self) -> None:
        peer = subprocess.Popen(
            [sys.executable, "-m", "node.main", "--config", str(self._write_peer_config())],
            cwd=PROJECT_ROOT,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self.processes.append(peer)
        peer_transport = self._transport(self.server_cert, self.server_key)
        peer_deadline = time.monotonic() + 8
        while time.monotonic() < peer_deadline:
            if peer.poll() is not None:
                self.fail("mTLS peer node exited during startup")
            try:
                peer_status = peer_transport.get_json(
                    f"https://127.0.0.1:{self.peer_port}", "/status", expected_peer_id=self.client_id
                )
                if peer_status.get("state") == "ACTIVE":
                    break
            except PeerRequestError:
                time.sleep(0.1)
        else:
            self.fail("mTLS peer node did not become ready")

        primary = subprocess.Popen(
            [sys.executable, "-m", "node.main", "--config", str(self._write_config())],
            cwd=PROJECT_ROOT,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self.processes.append(primary)
        transport = self._transport(self.client_cert, self.client_key)
        deadline = time.monotonic() + 8
        last_error = "no request attempted"
        while time.monotonic() < deadline:
            if primary.poll() is not None:
                self.fail("mTLS node exited during startup")
            try:
                status = transport.get_json(
                    f"https://127.0.0.1:{self.port}", "/status", expected_peer_id=self.server_id
                )
                if status.get("state") == "ACTIVE":
                    return
            except PeerRequestError as exc:
                last_error = str(exc)
                time.sleep(0.1)
        self.log.flush()
        self.fail(
            f"mTLS node did not become ready; last error: {last_error}; "
            f"node log: {self.log_path.read_text(encoding='utf-8')}"
        )

    def test_tls_and_certificate_identity_are_enforced(self) -> None:
        self._start_and_wait()
        endpoint = f"https://127.0.0.1:{self.port}"
        allowed_client = self._transport(self.client_cert, self.client_key)
        peers = allowed_client.get_json(endpoint, "/peers", expected_peer_id=self.server_id)["peers"]
        self.assertEqual([peer["node_id"] for peer in peers], [self.client_id])
        self.assertTrue(any(peer["state"] == "ALIVE" for peer in peers))
        peer_transport = self._transport(self.server_cert, self.server_key)
        peer_records = peer_transport.get_json(
            f"https://127.0.0.1:{self.peer_port}", "/peers", expected_peer_id=self.client_id
        )["peers"]
        self.assertTrue(
            any(peer["node_id"] == self.server_id and peer["state"] == "ALIVE" for peer in peer_records)
        )

        dashboard = Dashboard(
            DashboardConfig(
                "127.0.0.1",
                _free_port(),
                1,
                (MonitoredNode("secure-node", endpoint, self.server_id),),
                None,
                None,
                None,
                self.ca_cert,
                self.dashboard_cert,
                self.dashboard_key,
            )
        )
        try:
            monitored = dashboard.snapshot()["nodes"][0]
            self.assertEqual(monitored["status"], "ACTIVE")
            self.assertEqual(monitored["node_id"], self.server_id)
        finally:
            dashboard.close()

        impostor = self._transport(self.other_cert, self.other_key)
        with self.assertRaisesRegex(PeerRequestError, "HTTP 403"):
            impostor.post_json(
                endpoint,
                "/hello",
                HelloRequest(
                    PROTOCOL_VERSION, self.client_id, "claimed-peer", "127.0.0.1", _free_port(),
                    advertised_scheme="https",
                ).to_dict(),
            )
        with self.assertRaisesRegex(PeerRequestError, "HTTP 403"):
            impostor.get_json(endpoint, "/status")


if __name__ == "__main__":
    unittest.main()
