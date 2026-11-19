"""HTTPS client for outbound node registration and reporting."""

from __future__ import annotations

import http.client
import json
import ssl
from pathlib import Path
from urllib.parse import urlsplit


class MonitorRequestError(RuntimeError):
    pass


class MonitorClient:
    def __init__(self, base_url: str, ca_file: Path, timeout_seconds: float = 5) -> None:
        self.base_url = base_url.rstrip("/")
        self._parsed = urlsplit(self.base_url)
        if (
            self._parsed.scheme != "https"
            or self._parsed.hostname is None
            or self._parsed.port is None
            or not 1 <= self._parsed.port <= 65535
            or self._parsed.path not in ("", "/")
            or self._parsed.query
            or self._parsed.fragment
            or self._parsed.username is not None
            or self._parsed.password is not None
        ):
            raise ValueError("monitor_url must be an HTTPS origin with an explicit port")
        if not ca_file.is_file():
            raise ValueError(f"monitor CA certificate does not exist: {ca_file}")
        self.timeout_seconds = timeout_seconds
        self._context = ssl.create_default_context(cafile=str(ca_file))

    def post(
        self,
        path: str,
        payload: dict[str, object],
        bearer_token: str | None = None,
    ) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"
        return self._request("POST", path, json.dumps(payload).encode("utf-8"), headers)

    def get(self, path: str, bearer_token: str) -> dict[str, object]:
        return self._request("GET", path, None, {"Authorization": f"Bearer {bearer_token}"})

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> dict[str, object]:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("monitor API path must be an absolute path without query or fragment")
        connection = http.client.HTTPSConnection(
            self._parsed.hostname,
            self._parsed.port,
            timeout=self.timeout_seconds,
            context=self._context,
        )
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(32769)
            if len(raw) > 32768:
                raise MonitorRequestError("monitor response exceeded 32 KiB")
            if not 200 <= response.status < 300:
                detail = raw.decode("utf-8", errors="replace")[:512]
                raise MonitorRequestError(f"monitor returned HTTP {response.status}: {detail}")
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise MonitorRequestError(f"monitor request failed: {exc}") from exc
        finally:
            connection.close()
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MonitorRequestError(f"monitor returned invalid JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise MonitorRequestError("monitor response must be a JSON object")
        return result
