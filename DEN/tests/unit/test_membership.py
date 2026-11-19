from __future__ import annotations

import unittest

from node.networking.membership import PeerRegistry, PeerState


class MembershipTests(unittest.TestCase):
    def test_peer_moves_through_suspect_unavailable_and_recovers(self) -> None:
        registry = PeerRegistry()
        peer = registry.upsert("peer-id", "peer", "127.0.0.1", 8102)
        self.assertEqual(peer.state, PeerState.ALIVE)

        self.assertEqual(registry.mark_missed("peer-id", 3).state, PeerState.SUSPECT)
        self.assertEqual(registry.mark_missed("peer-id", 3).state, PeerState.SUSPECT)
        self.assertEqual(registry.mark_missed("peer-id", 3).state, PeerState.UNAVAILABLE)
        self.assertEqual(registry.mark_alive("peer-id").state, PeerState.ALIVE)
        self.assertEqual(registry.get("peer-id").missed_heartbeats, 0)


if __name__ == "__main__":
    unittest.main()
