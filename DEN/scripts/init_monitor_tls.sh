#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: %s <linux-laptop-private-ip> [dns-name]\n' "$0" >&2
    exit 2
fi

server_ip="$1"
dns_name="${2:-}"
python3 -c 'import ipaddress,sys; ipaddress.ip_address(sys.argv[1])' "$server_ip"
if [[ -n "$dns_name" && ! "$dns_name" =~ ^[A-Za-z0-9.-]+$ ]]; then
    printf 'DNS name may contain only letters, digits, dot, and hyphen\n' >&2
    exit 2
fi

mkdir -p certs runtime
chmod 700 certs
if [[ -e certs/den-ca.key || -e certs/den-ca.crt || -e certs/monitor.key || -e certs/monitor.crt ]]; then
    printf 'Refusing to overwrite existing CA or monitor credentials in DEN/certs\n' >&2
    exit 1
fi

openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout certs/den-ca.key -out certs/den-ca.crt -days 365 \
    -subj '/CN=DEN-LAN-Test-CA' \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign'
openssl req -new -newkey rsa:3072 -nodes \
    -keyout certs/monitor.key -out runtime/monitor.csr \
    -subj '/CN=DEN-Monitor'
chmod 600 certs/den-ca.key certs/monitor.key
{
    printf 'basicConstraints=CA:FALSE\n'
    printf 'keyUsage=digitalSignature,keyEncipherment\n'
    printf 'extendedKeyUsage=serverAuth\n'
    printf 'subjectAltName=IP:%s' "$server_ip"
    if [[ -n "$dns_name" ]]; then
        printf ',DNS:%s' "$dns_name"
    fi
    printf '\n'
} >runtime/monitor.ext
openssl x509 -req -in runtime/monitor.csr \
    -CA certs/den-ca.crt -CAkey certs/den-ca.key -CAcreateserial \
    -out certs/monitor.crt -days 90 -sha256 -extfile runtime/monitor.ext
printf 'Created a private test CA and monitor TLS certificate.\n'
printf 'Keep DEN/certs/den-ca.key private; distribute only DEN/certs/den-ca.crt to nodes.\n'
