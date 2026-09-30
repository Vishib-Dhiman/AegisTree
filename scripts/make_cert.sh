#!/usr/bin/env bash
# Self-signed TLS certificate for serving ClearSky to other devices on the LAN.
# Covers localhost, 127.0.0.1 and this machine's current LAN IP; regenerated
# automatically when the LAN IP changes. Output: .aegis/tls/{cert,key}.pem
set -euo pipefail
cd "$(dirname "$0")/.."

TLS_DIR=".aegis/tls"
CERT="$TLS_DIR/cert.pem"
KEY="$TLS_DIR/key.pem"

lan_ip() {
  if command -v ipconfig >/dev/null 2>&1; then  # macOS
    for iface in en0 en1 en2; do
      ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
      [ -n "$ip" ] && { echo "$ip"; return; }
    done
  fi
  if command -v hostname >/dev/null 2>&1; then  # Linux
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}

IP="$(lan_ip)"
if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  if [ -z "$IP" ] || openssl x509 -in "$CERT" -noout -text 2>/dev/null | grep -q "IP Address:$IP"; then
    echo "$CERT"
    exit 0
  fi
  echo "LAN IP is now $IP; regenerating the certificate." >&2
fi

mkdir -p "$TLS_DIR"
chmod 700 "$TLS_DIR"
SAN="DNS:localhost,IP:127.0.0.1"
[ -n "$IP" ] && SAN="$SAN,IP:$IP"
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 825 \
  -keyout "$KEY" -out "$CERT" \
  -subj "/CN=ClearSky" -addext "subjectAltName=$SAN" >/dev/null 2>&1
chmod 600 "$KEY"
echo "Created $CERT for $SAN" >&2
echo "$CERT"
