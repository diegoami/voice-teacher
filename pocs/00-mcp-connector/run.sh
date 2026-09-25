#!/usr/bin/env bash
# Start the lesson connector and a Cloudflare quick tunnel; print the URL to
# paste into claude.ai → Settings → Connectors → Add custom connector.
# The quick-tunnel host changes on every run, so the connector must be
# re-added (or edited) each time. Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
# Any free local port will do: only the tunnel address is public. Set PORT to force one.
PORT="${PORT:-$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')}"
mkdir -p data

if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  echo "Port $PORT is already in use:" >&2
  ss -ltnp "sport = :$PORT" >&2
  exit 1
fi

uv run python -m connector serve --port "$PORT" "$@" > data/server.log 2>&1 &
SERVER=$!
TUNNEL=""
trap 'kill $SERVER $TUNNEL 2>/dev/null' EXIT

for _ in $(seq 30); do
  kill -0 "$SERVER" 2>/dev/null || { echo "Server failed to start; see data/server.log" >&2; exit 1; }
  curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 1
done

cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" 2> data/tunnel.log &
TUNNEL=$!
HOST=""
for _ in $(seq 60); do
  HOST=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' data/tunnel.log | head -1 || true)
  [ -n "$HOST" ] && break
  kill -0 "$TUNNEL" 2>/dev/null || break
  sleep 1
done
[ -n "$HOST" ] || { echo "Tunnel did not start; see data/tunnel.log" >&2; exit 1; }

URL="$HOST/$(cat data/token)/mcp"
echo "Waiting for the public URL to answer..."
for _ in $(seq 60); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' -d '{}' "$URL" || true)
  [ "$CODE" != "000" ] && [ "$CODE" != "530" ] && [ "$CODE" != "502" ] && break
  sleep 2
done
if [ "$CODE" = "000" ] || [ "$CODE" = "530" ] || [ "$CODE" = "502" ]; then
  echo "The tunnel never became reachable (last HTTP $CODE); see data/tunnel.log" >&2
  exit 1
fi

echo "Ready. Connector URL (keep it private): $URL"
echo "Server log: data/server.log   Sessions: data/sessions/"
wait -n "$SERVER" "$TUNNEL" || true
echo "The connector stopped: the server or the tunnel exited. See data/server.log and data/tunnel.log." >&2
