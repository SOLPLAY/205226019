"""Serve a read-only node health dashboard on localhost."""

from __future__ import annotations

import argparse
import io
import json
import logging
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qrcode
from qrcode.image.svg import SvgPathImage

from dashboard.config import DashboardConfig, MonitoredNode, load_config
from monitor.client import MonitorClient, MonitorRequestError
from node.networking.transport import HttpTransport, PeerRequestError


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DEN Network Monitor</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--card:#111c2e;--line:#253550;--muted:#9aabc2;--text:#edf4ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif}
main{max-width:1100px;margin:40px auto;padding:0 20px}h1{margin-bottom:4px}.sub{color:var(--muted);margin:0 0 24px}
#summary{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}.pill,.card{background:var(--card);border:1px solid var(--line);border-radius:12px}
.pill{padding:9px 14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{padding:18px}.title{display:flex;justify-content:space-between;align-items:center;gap:12px}
.state{font-weight:700}.alive{color:#5ee0a0}.suspect{color:#ffd166}.unavailable,.unreachable,.identity-mismatch{color:#ff7373}
.details{color:var(--muted);font-size:13px;overflow-wrap:anywhere}.peers{border-top:1px solid var(--line);margin-top:14px;padding-top:10px}
.peer{display:flex;justify-content:space-between;gap:12px;padding:5px 0}.error{color:#ff9c9c}footer{color:var(--muted);margin-top:20px;font-size:13px}
button{background:#234c78;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px 14px;cursor:pointer;margin-bottom:16px}
.pairing{max-width:500px;margin-bottom:18px}.pairing img{width:280px;max-width:100%;background:#fff;padding:10px;border-radius:8px}.pairing p{overflow-wrap:anywhere}
</style>
</head>
<body><main><h1>DEN Network Monitor</h1>
<p class="sub">Read-only, local dashboard · observations are each node's local view</p>
<button id="pairButton" type="button">Pair a device</button>
<section id="pairing" class="card pairing" hidden>
<strong>Scan this QR code in the DEN app, or enter the details manually.</strong>
<p id="pairDetails" class="details">Loading pairing details…</p>
<img id="pairQr" alt="DEN device pairing QR code">
</section>
<div id="summary" aria-live="polite"></div><section id="nodes" class="grid"></section>
<footer id="updated">Connecting to configured nodes…</footer></main>
<script>
const summary=document.querySelector('#summary'), nodes=document.querySelector('#nodes'), updated=document.querySelector('#updated');
const pairing=document.querySelector('#pairing'), pairDetails=document.querySelector('#pairDetails');
document.querySelector('#pairButton').addEventListener('click',async()=>{
 pairing.hidden=false;pairDetails.textContent='Loading pairing details…';
 try{
  const response=await fetch('/api/pairing',{cache:'no-store'});
  if(!response.ok)throw new Error(`Pairing API returned ${response.status}`);
  const data=await response.json();
  pairDetails.textContent=`Monitor: ${data.monitor_url} · Enrollment code: ${data.enrollment_code}`;
  document.querySelector('#pairQr').src='/api/pairing-qr';
 }catch(e){pairDetails.textContent=`Could not load pairing information: ${e.message}`}
});
function element(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e}
function render(data){
 const counts={ACTIVE:0,DEGRADED:0,UNREACHABLE:0};
 for(const item of data.nodes){counts[item.status]=(counts[item.status]||0)+1}
 summary.replaceChildren(...Object.entries(counts).map(([k,v])=>element('span',`${k}: ${v}`,'pill')));
 nodes.replaceChildren(...data.nodes.map(item=>{
  const card=element('article',undefined,'card'), heading=element('div',undefined,'title');
  heading.append(element('strong',item.name),element('span',item.status,item.status.toLowerCase().replaceAll('_','-')));
  card.append(heading);
  if(item.node_id)card.append(element('p',`NodeID: ${item.node_id}`,'details'));
  if(item.state)card.append(element('p',`Node state: ${item.state} · Uptime: ${Number(item.uptime_seconds||0).toFixed(1)} s`,'details'));
  if(item.platform)card.append(element('p',`Platform: ${item.platform}`,'details'));
  if(item.last_seen_age_seconds!==undefined&&item.last_seen_age_seconds!==null)card.append(element('p',`Last report: ${Number(item.last_seen_age_seconds).toFixed(1)} s ago`,'details'));
  if(item.error)card.append(element('p',item.error,'details error'));
  const peerBox=element('div',undefined,'peers');
  peerBox.append(element('strong',`Peers (${item.peers.length})`));
  if(item.peers.length===0)peerBox.append(element('p','No peers reported','details'));
  for(const peer of item.peers){const row=element('div',undefined,'peer');row.append(element('span',peer.node_name),element('span',peer.state,peer.state.toLowerCase()));peerBox.append(row)}
  card.append(peerBox);return card
 }));
 updated.textContent=`Last poll: ${new Date(data.checked_at).toLocaleTimeString()} · Polls every 2 seconds`;
}
async function poll(){try{const response=await fetch('/api/nodes',{cache:'no-store'});if(!response.ok)throw new Error(`Dashboard API returned ${response.status}`);render(await response.json())}catch(e){updated.textContent=`Dashboard polling failed: ${e.message}`}}
poll();setInterval(poll,2000);
</script></body></html>"""


class Dashboard:
    def __init__(self, config: DashboardConfig) -> None:
        self.config = config
        self.transport = HttpTransport(
            config.poll_timeout_seconds,
            config.tls_ca_file,
            config.tls_cert_file,
            config.tls_key_file,
        )
        self.monitor_client: MonitorClient | None = None
        self.monitor_token: str | None = None
        if config.monitor_server_url is not None:
            if config.monitor_api_token_file is None or config.monitor_ca_file is None:
                raise ValueError("monitor API token and CA certificate are required")
            if stat.S_IMODE(config.monitor_api_token_file.stat().st_mode) & 0o077:
                raise ValueError("monitor API token file must be private (use chmod 600)")
            self.monitor_token = config.monitor_api_token_file.read_text(encoding="utf-8").strip()
            if not self.monitor_token:
                raise ValueError("monitor API token file is empty")
            self.monitor_client = MonitorClient(
                config.monitor_server_url, config.monitor_ca_file, config.poll_timeout_seconds
            )
        self.executor = ThreadPoolExecutor(max_workers=max(1, min(len(config.nodes), 16)))

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)

    def snapshot(self) -> dict[str, object]:
        if self.monitor_client is not None and self.monitor_token is not None:
            try:
                response = self.monitor_client.get("/api/v1/nodes", self.monitor_token)
                nodes = response.get("nodes")
                if not isinstance(nodes, list):
                    raise MonitorRequestError("monitor registry response did not contain a node list")
                return {"checked_at": datetime.now(timezone.utc).isoformat(), "nodes": nodes}
            except MonitorRequestError as exc:
                return {
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "nodes": [{
                        "name": "DEN monitoring server",
                        "status": "UNREACHABLE",
                        "state": None,
                        "uptime_seconds": 0.0,
                        "node_id": None,
                        "peers": [],
                        "error": str(exc),
                    }],
                }
        futures = [self.executor.submit(self._read_node, node) for node in self.config.nodes]
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [future.result() for future in futures],
        }

    def pairing_bundle(self) -> dict[str, str]:
        if self.monitor_client is None or self.monitor_token is None:
            raise ValueError("device pairing requires coordinator-backed dashboard configuration")
        response = self.monitor_client.get("/api/v1/pairing", self.monitor_token)
        monitor_url = response.get("monitor_url")
        enrollment_code = response.get("enrollment_code")
        ca_certificate = response.get("ca_certificate_pem")
        if (
            not isinstance(monitor_url, str)
            or not monitor_url
            or not isinstance(enrollment_code, str)
            or not enrollment_code
            or not isinstance(ca_certificate, str)
            or not ca_certificate
        ):
            raise MonitorRequestError("monitor returned incomplete pairing details")
        return {
            "type": "den-pairing-v1",
            "monitor_url": monitor_url,
            "enrollment_code": enrollment_code,
            "ca_certificate_pem": ca_certificate,
        }

    def pairing_qr_svg(self) -> bytes:
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=4,
        )
        qr.add_data(json.dumps(self.pairing_bundle(), separators=(",", ":")))
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        output = io.BytesIO()
        image.save(output)
        return output.getvalue()

    def _read_node(self, node: MonitoredNode) -> dict[str, object]:
        result: dict[str, object] = {
            "name": node.name,
            "endpoint": node.endpoint,
            "node_id": node.expected_node_id,
            "status": "UNREACHABLE",
            "state": None,
            "uptime_seconds": 0.0,
            "peers": [],
            "error": None,
        }
        try:
            status = self.transport.get_json(
                node.endpoint, "/status", expected_peer_id=node.expected_node_id
            )
            actual_id = status.get("node_id")
            if not isinstance(actual_id, str):
                raise PeerRequestError("status response did not contain a NodeID")
            if node.expected_node_id is not None and actual_id != node.expected_node_id:
                result["status"] = "IDENTITY_MISMATCH"
                result["node_id"] = actual_id
                result["error"] = "reported NodeID differs from configured NodeID"
                return result
            peer_response = self.transport.get_json(node.endpoint, "/peers", expected_peer_id=actual_id)
            peers = peer_response.get("peers")
            if not isinstance(peers, list):
                raise PeerRequestError("peer response did not contain a peer list")
            result.update(
                node_id=actual_id,
                status=status.get("state", "UNKNOWN"),
                state=status.get("state"),
                uptime_seconds=float(status.get("uptime_seconds", 0)),
                peers=peers,
            )
        except (PeerRequestError, OSError, ValueError, TypeError) as exc:
            result["error"] = str(exc)
        return result

    def make_server(self) -> ThreadingHTTPServer:
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                logging.getLogger("den.dashboard.http").debug(format, *args)

            def do_GET(self) -> None:
                if self.path == "/":
                    body = PAGE.encode("utf-8")
                    content_type = "text/html; charset=utf-8"
                elif self.path == "/api/nodes":
                    body = json.dumps(dashboard.snapshot()).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                elif self.path == "/api/pairing":
                    body = json.dumps(dashboard.pairing_bundle()).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                elif self.path == "/api/pairing-qr":
                    body = dashboard.pairing_qr_svg()
                    content_type = "image/svg+xml"
                else:
                    body = b'{"error":"not found"}'
                    content_type = "application/json; charset=utf-8"
                    self.send_response(404)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(body)

        return ThreadingHTTPServer((self.config.listen_host, self.config.listen_port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local DEN monitoring dashboard.")
    parser.add_argument("--config", required=True, help="path to dashboard YAML configuration")
    args = parser.parse_args()
    dashboard = None
    try:
        config = load_config(args.config)
        dashboard = Dashboard(config)
        server = dashboard.make_server()
        logging.info("DEN dashboard listening at http://%s:%s", config.listen_host, config.listen_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
            dashboard.close()
    except (OSError, ValueError) as exc:
        logging.error("dashboard could not start: %s", exc)
        if dashboard is not None:
            dashboard.close()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
