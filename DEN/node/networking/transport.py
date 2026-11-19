"""Bounded HTTP/JSON transport for peer requests."""

from __future__ import annotations

import http.client
import ipaddress
import json
import ssl
from pathlib import Path
from urllib.parse import urlsplit


class PeerRequestError(RuntimeError):
    pass


class HttpTransport:
    def __init__(
        self,
        timeout_seconds: float,
        ca_file: Path | None = None,
        cert_file: Path | None = None,
        key_file: Path | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.ca_file = ca_file
        self.cert_file = cert_file
        self.key_file = key_file

    def post_json(
        self,
        endpoint: str,
        path: str,
        payload: dict[str, object],
        expected_peer_id: str | None = None,
    ) -> dict[str, object]:
        return self._request("POST", endpoint, path, payload, expected_peer_id)

    def get_json(
        self,
        endpoint: str,
        path: str,
        expected_peer_id: str | None = None,
    ) -> dict[str, object]:
        return self._request("GET", endpoint, path, None, expected_peer_id)

    def _request(
        self,
        method: str,
        endpoint: str,
        path: str,
        payload: dict[str, object] | None,
        expected_peer_id: str | None,
    ) -> dict[str, object]:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ("http", "https") or parsed.hostname is None:
            raise PeerRequestError(f"invalid peer endpoint: {endpoint}")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise PeerRequestError(f"invalid peer port: {parsed.port}")
        if parsed.scheme == "https" and any(
            value is None for value in (self.ca_file, self.cert_file, self.key_file)
        ):
            raise PeerRequestError("HTTPS peer requires configured CA and client certificate")
        try:
            peer_is_loopback = (
                parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
            )
        except ValueError:
            peer_is_loopback = False
        if parsed.scheme == "http" and not peer_is_loopback:
            raise PeerRequestError("unencrypted HTTP is permitted only for loopback peers")
        connection: http.client.HTTPConnection
        if parsed.scheme == "https":
            context = ssl.create_default_context(cafile=str(self.ca_file))
            context.load_cert_chain(certfile=str(self.cert_file), keyfile=str(self.key_file))
            connection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=self.timeout_seconds, context=context
            )
        else:
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=self.timeout_seconds)
        request_path = f"{parsed.path.rstrip('/')}{path}"
        if parsed.query or parsed.fragment:
            raise PeerRequestError("peer endpoint must not contain a query or fragment")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        try:
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(method, request_path, body=body, headers=headers)
            peer_certificate = connection.sock.getpeercert() if parsed.scheme == "https" and connection.sock else None
            response = connection.getresponse()
            raw_body = response.read(65537)
            if len(raw_body) > 65536:
                raise PeerRequestError("peer response exceeded 64 KiB")
            if not 200 <= response.status < 300:
                raise PeerRequestError(f"peer returned HTTP {response.status}")
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise PeerRequestError(f"peer request failed: {exc}") from exc
        finally:
            connection.close()
        try:
            result = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PeerRequestError(f"peer returned invalid JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise PeerRequestError("peer response must be a JSON object")
        if parsed.scheme == "https":
            certificate_id = _certificate_common_name(peer_certificate)
            response_id = result.get("node_id", result.get("responder_node_id", expected_peer_id))
            if response_id is None:
                response_id = expected_peer_id
            if not isinstance(response_id, str) or certificate_id != response_id:
                raise PeerRequestError("peer TLS certificate identity does not match response identity")
            if expected_peer_id is not None and certificate_id != expected_peer_id:
                raise PeerRequestError("peer TLS certificate identity does not match expected NodeID")
        return result


def _certificate_common_name(certificate: dict[str, object] | None) -> str | None:
    if certificate is None:
        return None
    common_names = []
    for rdn in certificate.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                common_names.append(value)
    return common_names[0] if len(common_names) == 1 else None