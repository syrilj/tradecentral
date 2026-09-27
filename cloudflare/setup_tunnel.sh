#!/usr/bin/env bash
# setup_tunnel.sh — configure Cloudflare Tunnel to expose the local
# TradeCentral API server behind Cloudflare Access.
#
# Usage:
#   bash cloudflare/setup_tunnel.sh <hostname> [port]
#
# Example:
#   bash cloudflare/setup_tunnel.sh tradecentral.example.com 8787
#
# Prerequisites:
#   - cloudflared installed (brew install cloudflared)
#   - Logged in:  cloudflared tunnel login
#   - The local API server running (tools/run_dashboard.sh)
#
# After setup, configure Cloudflare Access in the Zero Trust dashboard
# (Access > Applications > Add) to restrict the hostname to your email.

set -euo pipefail

HOSTNAME="${1:?Usage: setup_tunnel.sh <hostname> [port]}"
PORT="${2:-8787}"
TUNNEL_NAME="tradecentral"
CONFIG_DIR="${HOME}/.cloudflared"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed. Install it first:" >&2
  echo "  brew install cloudflared" >&2
  exit 1
fi

if [ ! -f "${CONFIG_DIR}/cert.pem" ]; then
  echo "Not logged in to Cloudflare. Run:" >&2
  echo "  cloudflared tunnel login" >&2
  exit 1
fi

echo "[1/4] Creating tunnel '${TUNNEL_NAME}' (or reusing existing)..."
if cloudflared tunnel list 2>/dev/null | grep -q "${TUNNEL_NAME}"; then
  echo "  Tunnel already exists."
  TUNNEL_ID="$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import json, sys
tunnels = json.load(sys.stdin)
for t in tunnels:
    if t.get('name') == '${TUNNEL_NAME}':
        print(t['id'])
        break
")"
else
  cloudflared tunnel create "${TUNNEL_NAME}"
  TUNNEL_ID="$(cloudflared tunnel list --output json 2>/dev/null | python3 -c "
import json, sys
tunnels = json.load(sys.stdin)
for t in tunnels:
    if t.get('name') == '${TUNNEL_NAME}':
        print(t['id'])
        break
")"
fi

if [ -z "${TUNNEL_ID}" ]; then
  echo "Failed to resolve tunnel ID." >&2
  exit 1
fi
echo "  Tunnel ID: ${TUNNEL_ID}"

echo "[2/4] Routing DNS for ${HOSTNAME}..."
cloudflared tunnel route dns "${TUNNEL_NAME}" "${HOSTNAME}" || true

echo "[3/4] Writing ${CONFIG_FILE}..."
cat > "${CONFIG_FILE}" << TUNNELCFG
tunnel: ${TUNNEL_ID}
credentials-file: ${CONFIG_DIR}/${TUNNEL_ID}.json

ingress:
  - hostname: ${HOSTNAME}
    service: http://127.0.0.1:${PORT}
    originRequest:
      connectTimeout: 30s
      noTLSVerify: true
      httpHostHeader: ${HOSTNAME}
  - service: http_status:404
TUNNELCFG

echo "[4/4] Starting tunnel..."
echo ""
echo "  The tunnel is now running. To keep it alive, either:"
echo "    cloudflared tunnel run ${TUNNEL_NAME}          # foreground"
echo "    cloudflared service install                    # launchd (macOS)"
echo ""
echo "  Next step — lock down access in the Cloudflare Zero Trust dashboard:"
echo "    https://one.dash.cloudflare.com → Access → Applications → Add"
echo "    Application domain: ${HOSTNAME}"
echo "    Policy: Allow → Emails → your email address"
echo ""
echo "  Then set EDGE_CORS_ORIGINS=https://${HOSTNAME} in .env before"
echo "  starting the API server so POST endpoints are not CSRF-blocked."
echo ""
cloudflared tunnel run "${TUNNEL_NAME}"
