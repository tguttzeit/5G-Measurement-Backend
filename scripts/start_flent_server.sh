#!/usr/bin/env bash
# Starts the server-side processes a Flent client needs to run baseline/RRUL
# tests against this host: netperf's netserver (throughput generation) and an
# irtt server (latency sampling under load). Flent itself has no daemon mode —
# it's the client-side orchestrator devices run.
set -euo pipefail

IRTT_PORT="${IRTT_PORT:-8080}"
NETSERVER_PORT="${NETSERVER_PORT:-12865}"
PID_DIR="${PID_DIR:-/run/flent-server}"

mkdir -p "$PID_DIR"

for bin in netserver irtt; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: '$bin' not found on PATH — install netperf and irtt first" >&2
    exit 1
  fi
done

if [ -f "$PID_DIR/netserver.pid" ] && kill -0 "$(cat "$PID_DIR/netserver.pid")" 2>/dev/null; then
  echo "netserver already running (pid $(cat "$PID_DIR/netserver.pid"))"
else
  netserver -p "$NETSERVER_PORT" -D &
  echo $! > "$PID_DIR/netserver.pid"
  echo "netserver started on port $NETSERVER_PORT (pid $!)"
fi

if [ -f "$PID_DIR/irtt.pid" ] && kill -0 "$(cat "$PID_DIR/irtt.pid")" 2>/dev/null; then
  echo "irtt server already running (pid $(cat "$PID_DIR/irtt.pid"))"
else
  # irtt has no daemonize mode of its own (unlike netserver's -D), so it's
  # backgrounded here the same way.
  irtt server -b ":$IRTT_PORT" &
  echo $! > "$PID_DIR/irtt.pid"
  echo "irtt server started on port $IRTT_PORT (pid $!)"
fi
