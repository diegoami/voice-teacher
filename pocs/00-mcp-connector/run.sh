#!/usr/bin/env bash
# Start the lesson connector and a Cloudflare quick tunnel; print the URL to
# paste into claude.ai → Settings → Connectors → Add custom connector.
# The quick-tunnel host changes on every run, so the connector must be
# re-added (or edited) each time. Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
mkdir -p data
uv run python -m connector serve --port "$PORT" "$@" > data/server.log 2>&1 &
SERVER=$!
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" 2> data/tunnel.log &
TUNNEL=$!
trap 'kill $SERVER $TUNNEL 2>/dev/null' EXIT
for _ in $(seq 60); do
  HOST=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' data/tunnel.log | head -1 || true)
  [ -n "$HOST" ] && break
  sleep 1
done
[ -n "$HOST" ] || { echo "tunnel did not start; see data/tunnel.log" >&2; exit 1; }
echo "Connector URL (keep it private): $HOST/$(cat data/token)/mcp"
echo "Server log: data/server.log   Sessions: data/sessions/"
wait $SERVER
