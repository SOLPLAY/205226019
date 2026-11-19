#!/usr/bin/python3

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
from pathlib import Path


CONFIG = Path("/etc/den")
DATA = Path("/var/lib/den")
CERTS = CONFIG / "certs"
PUBLIC_CA = CONFIG / "den-ca.crt"


def _private_ipv4() -> str:
    output = subprocess.run(
        ["ip", "-o", "-4", "addr", "show", "scope", "global"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for line in output.splitlines():
        match = re.search(r"\binet\s+([0-9.]+)/", line)
        if match:
            address = ipaddress.ip_address(match.group(1))
            if address.is_private and not address.is_loopback and not address.is_link_local:
                return str(address)
    raise RuntimeError("No private IPv4 address found; connect to Wi-Fi or Ethernet and retry.")


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _create_certificates(ip: str) -> None:
    ca_key, ca_cert = CERTS / "den-ca.key", CERTS / "den-ca.crt"
    server_key, server_cert = CERTS / "monitor.key", CERTS / "monitor.crt"
    existing = [path.exists() for path in (ca_key, ca_cert, server_key, server_cert)]
    if all(existing):
        if not PUBLIC_CA.exists():
            PUBLIC_CA.write_bytes(ca_cert.read_bytes())
            PUBLIC_CA.chmod(0o644)
        return
    if any(existing):
        raise RuntimeError(f"Incomplete monitor certificate set in {CERTS}; refusing to overwrite.")

    csr, extensions = DATA / "monitor.csr", DATA / "monitor.ext"
    _run(
        "openssl", "req", "-x509", "-newkey", "rsa:4096", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert), "-days", "365",
        "-subj", "/CN=DEN-LAN-Test-CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    _run(
        "openssl", "req", "-new", "-newkey", "rsa:3072", "-nodes",
        "-keyout", str(server_key), "-out", str(csr),
        "-subj", "/CN=DEN-Monitor",
    )
    extensions.write_text(
        "basicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName=IP:{ip}\n",
        encoding="utf-8",
    )
    _run(
        "openssl", "x509", "-req", "-in", str(csr),
        "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
        "-out", str(server_cert), "-days", "90", "-sha256",
        "-extfile", str(extensions),
    )
    ca_key.chmod(0o600)
    server_key.chmod(0o600)
    os.chown(server_key, DEN_UID, DEN_GID)
    os.chown(server_cert, 0, DEN_GID)
    os.chown(ca_cert, 0, DEN_GID)
    server_cert.chmod(0o640)
    ca_cert.chmod(0o640)
    PUBLIC_CA.write_bytes(ca_cert.read_bytes())
    os.chown(PUBLIC_CA, 0, 0)
    PUBLIC_CA.chmod(0o644)


def _write_if_missing(path: Path, value: str, mode: int = 0o600) -> bool:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(value)
        file.write("\n")
    return True


def main() -> int:
    global DEN_GID
    import grp

    os.umask(0o077)
    DEN_GID = grp.getgrnam("den").gr_gid
    CONFIG.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    CERTS.mkdir(parents=True, exist_ok=True)
    os.chown(DATA, DEN_UID, DEN_GID)
    os.chown(CERTS, 0, DEN_GID)
    CERTS.chmod(0o750)

    ip = _private_ipv4()
    _create_certificates(ip)
    enrollment_created = _write_if_missing(
        DATA / "enrollment-code", subprocess.check_output(["openssl", "rand", "-hex", "24"], text=True).strip()
    )
    dashboard_created = _write_if_missing(
        DATA / "dashboard-token", subprocess.check_output(["openssl", "rand", "-hex", "32"], text=True).strip()
    )
    for name in ("enrollment-code", "dashboard-token"):
        os.chown(DATA / name, DEN_UID, DEN_GID)

    _write_if_missing(
        CONFIG / "monitor.yaml",
        f"listen_host: 0.0.0.0\n"
        f"listen_port: 8443\n"
        f"database_path: {DATA / 'monitor.sqlite3'}\n"
        f"enrollment_code_file: {DATA / 'enrollment-code'}\n"
        f"dashboard_token_file: {DATA / 'dashboard-token'}\n"
        f"tls_cert_file: {CERTS / 'monitor.crt'}\n"
        f"tls_key_file: {CERTS / 'monitor.key'}\n"
        f"tls_ca_file: {CERTS / 'den-ca.crt'}\n"
        "heartbeat_interval_seconds: 5\n"
        "suspect_after_seconds: 12\n"
        "unavailable_after_seconds: 25\n"
        "max_enrollments: 3\n",
        0o640,
    )
    _write_if_missing(
        CONFIG / "dashboard.yaml",
        "listen_host: 127.0.0.1\n"
        "listen_port: 8765\n"
        "poll_timeout_seconds: 3\n"
        f"monitor_server_url: https://{ip}:8443\n"
        f"monitor_api_token_file: {DATA / 'dashboard-token'}\n"
        f"monitor_ca_file: {CERTS / 'den-ca.crt'}\n",
        0o640,
    )
    os.chown(CONFIG, 0, 0)
    os.chmod(CONFIG, 0o755)
    for config in (CONFIG / "monitor.yaml", CONFIG / "dashboard.yaml"):
        if config.exists():
            os.chown(config, 0, DEN_GID)
            config.chmod(0o640)
    if enrollment_created:
        print(f"DEN enrollment code: {(DATA / 'enrollment-code').read_text(encoding='utf-8').strip()}")
    if dashboard_created:
        print("DEN dashboard token is stored in /var/lib/den/dashboard-token.")
    print(f"DEN monitor address: https://{ip}:8443")
    return 0


DEN_UID = 0
DEN_GID = 0
if __name__ == "__main__":
    import pwd

    DEN_UID = pwd.getpwnam("den").pw_uid
    raise SystemExit(main())
