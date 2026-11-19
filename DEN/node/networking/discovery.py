"""Periodic bootstrap and bounded peer exchange."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit

from node.config import NodeConfig
from node.networking.membership import PeerRegistry
from node.networking.transport import HttpTransport, PeerRequestError
from protocols.messages import HelloRequest, HelloResponse, PROTOCOL_VERSION


class PeerDiscovery:
    def __init__(
        self,
        config: NodeConfig,
        node_id: str,
        registry: PeerRegistry,
        transport: HttpTransport,
    ) -> None:
        self.config = config
        self.node_id = node_id
        self.registry = registry
        self.transport = transport
        self.logger = logging.getLogger("den.discovery")

    def is_trusted(self, node_id: str) -> bool:
        return "*" in self.config.trusted_peer_ids or node_id in self.config.trusted_peer_ids

    async def run(self) -> None:
        while True:
            await self.discover_once()
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def discover_once(self) -> None:
        candidates = set(self.config.bootstrap_peers)
        for record in self.registry.list():
            candidates.add(f"{record.scheme}://{record.host}:{record.port}")
        for endpoint in sorted(candidates):
            try:
                response_data = await asyncio.to_thread(
                    self.transport.post_json,
                    endpoint,
                    "/hello",
                    HelloRequest(
                        protocol_version=PROTOCOL_VERSION,
                        node_id=self.node_id,
                        node_name=self.config.node_name,
                        advertised_host=self.config.advertised_host,
                        advertised_port=self.config.listen_port,
                        advertised_scheme="https" if self.config.tls_cert_file else "http",
                    ).to_dict(),
                )
                response = HelloResponse.from_dict(response_data)
                if not response.accepted or response.node_id == self.node_id:
                    continue
                if not self.is_trusted(response.node_id):
                    self.logger.warning(
                        "hello rejected: peer identity is not in trusted_peer_ids",
                        extra={"node_id": self.node_id, "peer_node_id": response.node_id},
                    )
                    continue
                host, port = _endpoint_parts(endpoint)
                self.registry.upsert(response.node_id, response.node_name, host, port, urlsplit(endpoint).scheme)
                for peer in response.known_peers:
                    if peer.node_id != self.node_id and self.is_trusted(peer.node_id):
                        self.registry.learn(peer.node_id, peer.node_name, peer.host, peer.port, peer.scheme)
            except (PeerRequestError, ValueError) as exc:
                self.logger.debug(
                    "peer discovery attempt failed",
                    extra={"node_id": self.node_id, "endpoint": endpoint, "error": str(exc)},
                )


def _endpoint_parts(endpoint: str) -> tuple[str, int]:
    parsed = urlsplit(endpoint)
    if parsed.hostname is None or parsed.port is None:
        raise ValueError(f"invalid peer endpoint: {endpoint}")
    return parsed.hostname, parsed.port