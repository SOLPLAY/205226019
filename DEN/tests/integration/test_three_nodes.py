from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard.config import DashboardConfig, MonitoredNode
from dashboard.main import Dashboard


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _free_ports(count: int) -> list[int]:
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [int(sock.getsockname()[1]) for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def _get_json(port: int, path: str) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=0.5) as response:
        return json.load(response)


class ThreeNodeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ports = _free_ports(3)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.log_files = []
        self.configs: dict[str, Path] = {}
        node_names = ("node-a", "node-b", "node-c")
        bootstrap_indexes = ((1,), (0, 2), (1,))
        for index, name in enumerate(node_names):
            peers = ", ".join(f"http://127.0.0.1:{self.ports[peer]}" for peer in bootstrap_indexes[index])
            config_path = self.root / f"{name}.yaml"
            config_path.write_text(
                f"node_name: {name}\n"
                f"data_dir: {self.root / name}\n"
                "listen_host: 127.0.0.1\n"
                f"listen_port: {self.ports[index]}\n"
                f"bootstrap_peers: [{peers}]\n"
                "trusted_peer_ids: ['*']\n"
                "heartbeat_interval_seconds: 0.2\n"
                "heartbeat_timeout_seconds: 0.1\n"
                "unavailable_after_misses: 3\n",
                encoding="utf-8",
            )
            self.configs[name] = config_path

    def tearDown(self) -> None:
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        for log_file in self.log_files:
            log_file.close()
        self.temporary.cleanup()

    def _start(self, name: str) -> subprocess.Popen[bytes]:
        log_file = (self.root / f"{name}-{len(self.log_files)}.log").open("wb")
        self.log_files.append(log_file)
        process = subprocess.Popen(
            [sys.executable, "-m", "node.main", "--config", str(self.configs[name])],
            cwd=PROJECT_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        self.processes[name] = process
        return process

    def _wait_until(self, predicate, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.1)
        return predicate()

    def _peer_states(self, node_index: int) -> dict[str, str]:
        response = _get_json(self.ports[node_index], "/peers")
        peers = response["peers"]
        return {peer["node_name"]: peer["state"] for peer in peers}

    def _node_is_active(self, node_index: int) -> bool:
        try:
            return _get_json(self.ports[node_index], "/status").get("state") == "ACTIVE"
        except OSError:
            return False

    def _node_peer_state(self, node_index: int, node_name: str) -> str | None:
        try:
            return self._peer_states(node_index).get(node_name)
        except OSError:
            return None

    def test_three_node_discovery_failure_and_rejoin(self) -> None:
        self._start("node-c")
        self._start("node-b")
        self._start("node-a")
        for index in range(3):
            self.assertTrue(
                self._wait_until(lambda index=index: self._node_is_active(index)),
                f"node at port {self.ports[index]} did not become active",
            )

        self.assertTrue(
            self._wait_until(lambda: {"node-b", "node-c"}.issubset(self._peer_states(0))),
            "node-a did not learn node-c through node-b",
        )
        node_ids = {
            _get_json(port, "/status")["node_id"]
            for port in self.ports
        }
        self.assertEqual(len(node_ids), 3)

        dashboard_config = DashboardConfig(
            "127.0.0.1",
            _free_ports(1)[0],
            0.5,
            tuple(
                MonitoredNode(name, f"http://127.0.0.1:{port}", None)
                for name, port in zip(("node-a", "node-b", "node-c"), self.ports)
            ),
            None,
            None,
            None,
            None,
            None,
            None,
        )
        dashboard = Dashboard(dashboard_config)
        dashboard_server = dashboard.make_server()
        dashboard_thread = threading.Thread(target=dashboard_server.serve_forever)
        dashboard_thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{dashboard_config.listen_port}/", timeout=1) as response:
                self.assertIn(b"DEN Network Monitor", response.read())
            with urlopen(
                f"http://127.0.0.1:{dashboard_config.listen_port}/api/nodes", timeout=2
            ) as response:
                dashboard_nodes = json.load(response)["nodes"]
            self.assertEqual({node["status"] for node in dashboard_nodes}, {"ACTIVE"})
            self.assertEqual(len(dashboard_nodes[0]["peers"]), 2)

            stopped = self.processes["node-c"]
            stopped.terminate()
            stopped.wait(timeout=3)
            self.assertTrue(
                self._wait_until(lambda: self._node_peer_state(0, "node-c") == "UNAVAILABLE"),
                "node-a did not mark stopped node-c unavailable",
            )
            unavailable = dashboard.snapshot()["nodes"]
            self.assertEqual(unavailable[2]["status"], "UNREACHABLE")

            self._start("node-c")
            self.assertTrue(
                self._wait_until(lambda: self._node_peer_state(0, "node-c") == "ALIVE"),
                "node-a did not recognize node-c after restart",
            )
            recovered = dashboard.snapshot()["nodes"]
            self.assertEqual(recovered[2]["status"], "ACTIVE")
        finally:
            dashboard_server.shutdown()
            dashboard_server.server_close()
            dashboard_thread.join(timeout=2)
            dashboard.close()

    def test_http_endpoint_rejects_untrusted_identity(self) -> None:
        config_path = self.configs["node-a"]
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace("trusted_peer_ids: ['*']", "trusted_peer_ids: []"),
            encoding="utf-8",
        )
        self._start("node-a")
        self.assertTrue(self._wait_until(lambda: self._node_is_active(0)))
        request = Request(
            f"http://127.0.0.1:{self.ports[0]}/hello",
            data=json.dumps(
                {
                    "protocol_version": 1,
                    "node_id": "untrusted-node",
                    "node_name": "untrusted",
                    "advertised_host": "127.0.0.1",
                    "advertised_port": 8999,
                    "capabilities": ["hello"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=1)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertEqual(_get_json(self.ports[0], "/peers")["peers"], [])


if __name__ == "__main__":
    unittest.main()
