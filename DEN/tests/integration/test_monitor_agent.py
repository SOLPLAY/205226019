from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from dashboard.config import DashboardConfig
from dashboard.main import Dashboard
from monitor.client import MonitorClient
from monitor.config import MonitorConfig
from monitor.server import MonitorServer
from node.agent import AgentConfig, NodeAgent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MonitorAgentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("openssl") is None:
            raise unittest.SkipTest("OpenSSL is required for the monitor-agent integration test")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ca_cert = self.root / "ca.crt"
        self.server_cert = self.root / "monitor.crt"
        self.server_key = self.root / "monitor.key"
        self._create_certificates()
        self.port = _free_port()
        self.node_name = "test-node"
        self.enrollment_code = "test-enrollment-" + uuid.uuid4().hex
        self.dashboard_token = "test-dashboard-" + uuid.uuid4().hex
        self.config = MonitorConfig(
            "127.0.0.1",
            self.port,
            self.root / "monitor.sqlite3",
            self.root / "enrollment-code",
            self.root / "dashboard-token",
            self.server_cert,
            self.server_key,
            self.ca_cert,
            0.1,
            0.4,
            0.8,
            3,
        )
        self.server = MonitorServer(self.config, self.enrollment_code, self.dashboard_token)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.agent = NodeAgent(
            AgentConfig(
                self.node_name,
                self.root / "node-data",
                f"https://127.0.0.1:{self.port}",
                self.ca_cert,
                0.1,
                "test",
            )
        )
        self.agent_thread = threading.Thread(
            target=self.agent.run, args=(self.enrollment_code,), daemon=True
        )
        self.agent_thread.start()
        self.client = MonitorClient(f"https://127.0.0.1:{self.port}", self.ca_cert, 0.5)

    def tearDown(self) -> None:
        self.agent.stop()
        self.agent_thread.join(timeout=3)
        self.server.shutdown()
        self.server_thread.join(timeout=3)
        self.temporary.cleanup()

    def _run_openssl(self, *args: str) -> None:
        subprocess.run(["openssl", *args], check=True, capture_output=True, text=True)

    def _create_certificates(self) -> None:
        self._run_openssl(
            "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(self.root / "ca.key"),
            "-out", str(self.ca_cert),
            "-subj", "/CN=Monitor-Agent-Test-CA",
            "-days", "2",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        )
        key = self.root / "monitor.key"
        csr = self.root / "monitor.csr"
        self._run_openssl(
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key),
            "-out", str(csr),
            "-subj", "/CN=DEN-Monitor",
        )
        key.chmod(0o600)
        extensions = self.root / "monitor.ext"
        extensions.write_text(
            "basicConstraints=CA:FALSE\n"
            "keyUsage=digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectAltName=IP:127.0.0.1\n",
            encoding="utf-8",
        )
        self._run_openssl(
            "x509", "-req", "-in", str(csr),
            "-CA", str(self.ca_cert), "-CAkey", str(self.root / "ca.key"),
            "-CAcreateserial", "-out", str(self.server_cert), "-days", "2",
            "-sha256", "-extfile", str(extensions),
        )

    def _wait_for_status(self, expected: str, timeout: float = 3) -> dict[str, object] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            nodes = self.client.get("/api/v1/nodes", self.dashboard_token)["nodes"]
            if nodes and nodes[0]["status"] == expected:
                return nodes[0]
            time.sleep(0.05)
        return None

    def test_outbound_enrollment_heartbeat_monitoring_and_offline_detection(self) -> None:
        active = self._wait_for_status("ACTIVE")
        self.assertIsNotNone(active)
        self.assertEqual(active["node_name"], self.node_name)
        self.assertTrue(active["platform"])
        self.assertTrue((self.root / "node-data" / "monitor-credential.json").is_file())
        pairing = self.client.get("/api/v1/pairing", self.dashboard_token)
        self.assertEqual(pairing["monitor_url"], f"https://127.0.0.1:{self.port}")
        self.assertEqual(pairing["enrollment_code"], self.enrollment_code)
        self.assertIn("BEGIN CERTIFICATE", pairing["ca_certificate_pem"])
        dashboard_token_file = self.root / "dashboard-token"
        dashboard_token_file.write_text(self.dashboard_token, encoding="utf-8")
        dashboard_token_file.chmod(0o600)
        dashboard = Dashboard(
            DashboardConfig(
                "127.0.0.1",
                8765,
                0.5,
                (),
                f"https://127.0.0.1:{self.port}",
                dashboard_token_file,
                self.ca_cert,
                None,
                None,
                None,
            )
        )
        try:
            dashboard_nodes = dashboard.snapshot()["nodes"]
            pairing = dashboard.pairing_bundle()
            pairing_qr = dashboard.pairing_qr_svg()
        finally:
            dashboard.close()
        self.assertEqual(dashboard_nodes[0]["node_name"], self.node_name)
        self.assertEqual(dashboard_nodes[0]["status"], "ACTIVE")
        self.assertEqual(pairing["type"], "den-pairing-v1")
        self.assertEqual(pairing["enrollment_code"], self.enrollment_code)
        self.assertIn(b"<svg", pairing_qr)
        self.assertEqual(
            self._wait_for_status("UNAVAILABLE", timeout=0.01),
            None,
        )

        self.agent.stop()
        self.agent_thread.join(timeout=3)
        unavailable = self._wait_for_status("UNAVAILABLE")
        self.assertIsNotNone(unavailable)
        self.assertGreaterEqual(unavailable["last_seen_age_seconds"], self.config.unavailable_after_seconds)

        self.agent = NodeAgent(self.agent.config)
        self.agent_thread = threading.Thread(target=self.agent.run, daemon=True)
        self.agent_thread.start()
        recovered = self._wait_for_status("ACTIVE")
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["node_id"], active["node_id"])


if __name__ == "__main__":
    unittest.main()
