#!/bin/sh
# Helper for the LAN dev stack (docker-compose.lan-dev.yml).
#
#   scripts/lan-dev.sh up <lan-ip-or-hostname>   build + start, seed the test device and admin
#   scripts/lan-dev.sh ca                        copy Caddy's root certificate to deploy/lan-dev/
#   scripts/lan-dev.sh logs [service]            follow logs
#   scripts/lan-dev.sh down                      stop (keeps data); add -v to wipe it
set -eu

cd "$(dirname "$0")/.."

ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-lan-dev-admin-pw}"
PORT="${DEV_PORT:-8443}"
CA_DIR="deploy/lan-dev"

# Only `up` needs the real address (it goes into the certificate); the other commands just need
# the variable to be set for compose to accept the file.
export DEV_HOST="${DEV_HOST:-localhost}"

compose() {
  docker compose -f docker-compose.lan-dev.yml "$@"
}

export_ca() {
  mkdir -p "$CA_DIR"
  compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$CA_DIR/lan-dev-root-ca.crt"
  echo "Root CA: $CA_DIR/lan-dev-root-ca.crt"
}

case "${1:-}" in
  up)
    [ -n "${2:-}" ] || { echo "Usage: $0 up <lan-ip-or-hostname>" >&2; exit 1; }
    export DEV_HOST="$2"
    compose up -d --build
    echo "Waiting for the backend..."
    until [ "$(compose ps --format '{{.Health}}' backend)" = "healthy" ]; do sleep 2; done
    compose exec -T backend python scripts/seed_dev_device.py
    compose exec -T backend python scripts/create_user.py "$ADMIN_USER" "$ADMIN_PASSWORD" --superuser || true
    # Caddy writes its root certificate when it first sets the site up.
    until export_ca >/dev/null 2>&1; do sleep 1; done
    export_ca
    echo
    echo "Dashboard:   https://$DEV_HOST:$PORT   (login: $ADMIN_USER / $ADMIN_PASSWORD)"
    echo "Heartbeat:   https://$DEV_HOST:$PORT/api/heartbeat"
    echo "Uploads:     https://$DEV_HOST:$PORT/api/measurements"
    ;;
  ca)
    export_ca
    ;;
  logs)
    shift
    compose logs -f "$@"
    ;;
  down)
    shift
    compose down "$@"
    ;;
  *)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
