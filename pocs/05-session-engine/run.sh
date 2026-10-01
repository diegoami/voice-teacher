#!/usr/bin/env bash
# Start the voice lesson server and a Cloudflare quick tunnel; print the HTTPS
# address to open on the phone (Chrome needs HTTPS for the microphone).
# The quick-tunnel host changes on every run. Stop with Ctrl+C.
# Usage: ./run.sh [lesson.json] [extra args for `python -m engine serve`]
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
LESSON="${1:-fixtures/lessons/4B.json}"
[ $# -gt 0 ] && shift
PORT="${PORT:-$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')}"
mkdir -p fixtures/logs

if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  echo "Port $PORT is already in use:" >&2
  ss -ltnp "sport = :$PORT" >&2
  exit 1
fi

uv run python -m engine serve "$LESSON" --port "$PORT" "$@" > fixtures/logs/server.log 2>&1 &
SERVER=$!
TUNNEL=""
trap 'kill $SERVER $TUNNEL 2>/dev/null' EXIT

for _ in $(seq 30); do
  kill -0 "$SERVER" 2>/dev/null || { echo "Server failed to start:" >&2; cat fixtures/logs/server.log >&2; exit 1; }
  curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 1
done

cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" 2> fixtures/logs/tunnel.log &
TUNNEL=$!
HOST=""
for _ in $(seq 60); do
  HOST=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' fixtures/logs/tunnel.log | head -1 || true)
  [ -n "$HOST" ] && break
  kill -0 "$TUNNEL" 2>/dev/null || break
  sleep 1
done
[ -n "$HOST" ] || { echo "Tunnel did not start; see fixtures/logs/tunnel.log" >&2; exit 1; }

URL="$HOST/$(cat fixtures/token)/"
echo "Waiting for the public URL to answer..."
CODE=000
for _ in $(seq 60); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "$URL" || true)
  [ "$CODE" = "200" ] && break
  sleep 2
done
if [ "$CODE" != "200" ]; then
  echo "The tunnel never became reachable (last HTTP $CODE); see fixtures/logs/tunnel.log" >&2
  exit 1
fi

echo "Ready. Open this on the phone (keep it private): $URL"
echo "Server log: fixtures/logs/server.log   Sessions: fixtures/sessions/"
wait -n "$SERVER" "$TUNNEL" || true
echo "Stopped: the server or the tunnel exited. See fixtures/logs/." >&2
