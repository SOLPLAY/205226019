from __future__ import annotations

import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from node.config import load_config
from node.identity import NodeIdentity
from node.networking.transport import HttpTransport, PeerRequestError
from protocols.messages import HeartbeatRequest, HelloRequest, PROTOCOL_VERSION


class ConfigIdentityProtocolTests(unittest.TestCase):
    def test_config_loads_and_rejects_invalid_peer_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "node.yaml"
            config_path.write_text(
                "node_name: test\n"
                "data_dir: data\n"
                "listen_host: 127.0.0.1\n"
                "listen_port: 8123\n"
                "bootstrap_peers: [http://127.0.0.1:8124]\n"
                "trusted_peer_ids: ['*']\n",
                encoding="utf-8",
            )
            config = load_config(config_path)
            self.assertEqual(config.listen_port, 8123)
            self.assertEqual(config.data_dir, Path(temporary) / "data")

            config_path.write_text(
                "node_name: test\n"
                "data_dir: data\n"
                "listen_host: 127.0.0.1\n"
                "listen_port: 8123\n"
                "bootstrap_peers: [ftp://127.0.0.1:8124]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid bootstrap peer"):
                load_config(config_path)

            config_path.write_text(
                "node_name: test\n"
                "data_dir: data\n"
                "listen_host: 0.0.0.0\n"
                "listen_port: 8123\n"
                "trusted_peer_ids: ['*']\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "advertised_host"):
                load_config(config_path)

            config_path.write_text(
                "node_name: remote\n"
                "data_dir: data\n"
                "listen_host: 10.1.2.3\n"
                "advertised_host: 10.1.2.3\n"
                "listen_port: 8123\n"
                "trusted_peer_ids: [peer-id]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "require mutual TLS"):
                load_config(config_path)

            config_path.write_text(
                "node_name: local\n"
                "data_dir: data\n"
                "listen_host: 127.0.0.1\n"
                "listen_port: 8123\n"
                "bootstrap_peers: [http://10.1.2.4:8124]\n"
                "trusted_peer_ids: ['*']\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "non-loopback bootstrap peers"):
                load_config(config_path)

            ca_file = Path(temporary) / "ca.crt"
            cert_file = Path(temporary) / "node.crt"
            key_file = Path(temporary) / "node.key"
            for tls_file in (ca_file, cert_file, key_file):
                tls_file.write_text("test", encoding="utf-8")
            key_file.chmod(0o600)
            config_path.write_text(
                "node_name: remote\n"
                "data_dir: data\n"
                "listen_host: 0.0.0.0\n"
                "advertised_host: 10.1.2.3\n"
                "listen_port: 8123\n"
                "bootstrap_peers: [https://10.1.2.4:8124]\n"
                "trusted_peer_ids: [peer-id]\n"
                f"tls_ca_file: {ca_file}\n"
                f"tls_cert_file: {cert_file}\n"
                f"tls_key_file: {key_file}\n",
                encoding="utf-8",
            )
            remote_config = load_config(config_path)
            self.assertTrue(remote_config.advertised_endpoint.startswith("https://10.1.2.3:"))
            with self.assertRaisesRegex(PeerRequestError, "only for loopback"):
                HttpTransport(0.1).get_json("http://10.1.2.4:8124", "/status")

    def test_identity_persists_isolates_and_locks_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_dir = Path(temporary) / "first"
            first = NodeIdentity.open(first_dir)
            first_id = first.node_id
            with self.assertRaisesRegex(RuntimeError, "already in use"):
                NodeIdentity.open(first_dir)
            first.close()

            restarted = NodeIdentity.open(first_dir)
            separate = NodeIdentity.open(Path(temporary) / "second")
            try:
                self.assertEqual(restarted.node_id, first_id)
                self.assertNotEqual(separate.node_id, first_id)
            finally:
                restarted.close()
                separate.close()

    def test_identity_can_be_initialized_before_tls_certificates_exist(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "remote-node.yaml"
            config_path.write_text(
                "node_name: remote-node\n"
                "data_dir: node-data\n"
                "listen_host: 0.0.0.0\n"
                "advertised_host: 10.1.2.3\n"
                "listen_port: 8123\n"
                "trusted_peer_ids: [peer-id]\n"
                "tls_ca_file: missing-ca.crt\n"
                "tls_cert_file: missing-node.crt\n"
                "tls_key_file: missing-node.key\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "node.main",
                    "--config",
                    str(config_path),
                    "--init-identity",
                ],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            )
            node_id = result.stdout.strip()
            self.assertTrue(node_id)
            self.assertEqual((Path(temporary) / "node-data" / "node-id").read_text().strip(), node_id)

    def test_message_round_trip_and_version_validation(self) -> None:
        hello = HelloRequest(PROTOCOL_VERSION, "node-id", "node", "127.0.0.1", 8123)
        self.assertEqual(HelloRequest.from_dict(hello.to_dict()), hello)
        heartbeat = HeartbeatRequest(PROTOCOL_VERSION, "node-id", 4, "2026-01-01T00:00:00Z")
        self.assertEqual(HeartbeatRequest.from_dict(heartbeat.to_dict()), heartbeat)
        invalid = heartbeat.to_dict()
        invalid["protocol_version"] = 99
        with self.assertRaisesRegex(ValueError, "unsupported protocol_version"):
            HeartbeatRequest.from_dict(invalid)


if __name__ == "__main__":
    unittest.main()
