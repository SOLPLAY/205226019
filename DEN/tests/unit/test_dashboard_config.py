from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dashboard.config import load_config


class DashboardConfigTests(unittest.TestCase):
    def test_dashboard_only_binds_loopback_and_requires_https_for_remote_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "dashboard.yaml"
            config_path.write_text(
                "listen_host: 0.0.0.0\n"
                "nodes:\n"
                "  - name: node\n"
                "    endpoint: http://10.1.2.3:8101\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "loopback"):
                load_config(config_path)

            config_path.write_text(
                "listen_host: 127.0.0.1\n"
                "nodes:\n"
                "  - name: node\n"
                "    endpoint: http://10.1.2.3:8101\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must use HTTPS"):
                load_config(config_path)

    def test_local_dashboard_configuration_loads(self) -> None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "dashboard.yaml"
        config = load_config(config_path)
        self.assertEqual(config.listen_host, "127.0.0.1")
        self.assertEqual(len(config.nodes), 3)
        self.assertTrue(all(node.endpoint.startswith("http://127.0.0.1:") for node in config.nodes))


if __name__ == "__main__":
    unittest.main()
