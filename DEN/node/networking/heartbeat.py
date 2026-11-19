"""Periodic heartbeat checks and peer health state changes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from node.config import NodeConfig
from node.networking.discovery import PeerDiscovery
from node.networking.membership import PeerRegistry, PeerState
from node.networking.transport import HttpTransport, PeerRequestError
from protocols.messages import HeartbeatRequest, HeartbeatResponse, PROTOCOL_VERSION


class HeartbeatMonitor:
    def __init__(
        self,
        config: NodeConfig,
        node_id: str,
        registry: PeerRegistry,
        transport: HttpTransport,
        discovery: PeerDiscovery,
    ) -> None:
        self.config = config
        self.node_id = node_id
        self.registry = registry
        self.transport = transport
        self.discovery = discovery
        self.logger = logging.getLogger("den.heartbeat")
        self._sequence = 0

    async def run(self) -> None:
        while True:
            for peer in self.registry.list():
                await self._check_peer(peer.node_id)
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def _check_peer(self, node_id: str) -> None:
        peer = self.registry.get(node_id)
        if peer is None or not self.discovery.is_trusted(node_id):
            return
        self._sequence += 1
        request = HeartbeatRequest(
            PROTOCOL_VERSION,
            self.node_id,
            self._sequence,
            datetime.now(timezone.utc).isoformat(),
        )
        previous_state = peer.state
        try:
            data = await asyncio.to_thread(
                self.transport.post_json,
                f"{peer.scheme}://{peer.host}:{peer.port}",
                "/heartbeat",
                request.to_dict(),
                expected_peer_id=node_id,
            )
            response = HeartbeatResponse.from_dict(data)
            if response.responder_node_id != node_id or response.echoed_sequence != request.sequence:
                raise PeerRequestError("heartbeat response identity or sequence did not match")
            updated = self.registry.mark_alive(node_id)
            if previous_state != PeerState.ALIVE:
                self.logger.info(
                    "peer health changed",
                    extra={
                        "node_id": self.node_id,
                        "peer_node_id": node_id,
                        "from_state": previous_state.value,
                        "to_state": updated.state.value,
                    },
                )
        except (PeerRequestError, ValueError) as exc:
            updated = self.registry.mark_missed(node_id, self.config.unavailable_after_misses)
            if updated.state != previous_state:
                self.logger.warning(
                    "peer health changed",
                    extra={
                        "node_id": self.node_id,
                        "peer_node_id": node_id,
                        "from_state": previous_state.value,
                        "to_state": updated.state.value,
                        "error": str(exc),
                    },
                )