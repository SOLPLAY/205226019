from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from monitor.registry import EnrollmentError, MonitorRegistry


class MonitorRegistryTests(unittest.TestCase):
    def test_enrollment_credentials_and_node_health_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = MonitorRegistry(
                Path(temporary) / "registry.sqlite3",
                "enrollment-secret",
                "dashboard-secret",
                1,
                1,
                3,
            )
            try:
                node_id = str(uuid.uuid4())
                with self.assertRaisesRegex(EnrollmentError, "invalid enrollment code"):
                    registry.enroll(node_id, "node", "wrong")
                credential = registry.enroll(node_id, "node", "enrollment-secret")
                with self.assertRaisesRegex(EnrollmentError, "already enrolled"):
                    registry.enroll(node_id, "node", "enrollment-secret")
                with self.assertRaisesRegex(EnrollmentError, "invalid node credential"):
                    registry.heartbeat(node_id, "wrong", {})
                with self.assertRaisesRegex(EnrollmentError, "does not match"):
                    registry.heartbeat(
                        node_id,
                        credential,
                        {
                            "node_name": "spoofed-name",
                            "uptime_seconds": 1,
                            "platform": "test",
                            "version": "test",
                            "peers": [],
                        },
                    )
                registry.heartbeat(
                    node_id,
                    credential,
                    {
                        "node_name": "node",
                        "uptime_seconds": 1,
                        "platform": "test",
                        "version": "test",
                        "peers": [],
                    },
                )
                self.assertEqual(registry.nodes()[0]["status"], "ACTIVE")
            finally:
                registry.close()


if __name__ == "__main__":
    unittest.main()
