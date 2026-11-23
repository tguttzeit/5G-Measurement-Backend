#!/usr/bin/env bash
# Dump the backend database from the running postgres container into BACKUP_DIR.
#
#   backup-db.sh               daily dump, run by 5gm-db-backup.timer
#   backup-db.sh --pre-update  dump before an update, kept apart from the daily rotation
#
# Retention is by count, not age, so a timer that stopped running never ages out the last good
# dumps. pg_dump runs inside the container with its own environment; this script holds no
# credentials.
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/5g-measurement-backend}
COMPOSE_DIR=${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
BACKUP_KEEP_DAILY=${BACKUP_KEEP_DAILY:-7}
BACKUP_KEEP_WEEKLY=${BACKUP_KEEP_WEEKLY:-4}
BACKUP_KEEP_PRE_UPDATE=${BACKUP_KEEP_PRE_UPDATE:-3}
BACKUP_MIN_FREE_MB=${BACKUP_MIN_FREE_MB:-5120}
DATABASE=measurement_backend

case "${1:-}" in
  "") kind=daily ;;
  --pre-update) kind=pre-update ;;
  *) echo "usage: $0 [--pre-update]" >&2; exit 2 ;;
esac

warn() {
  # systemd reads a leading <N> on a line as its journal priority (4 = warning).
  if [[ -n ${JOURNAL_STREAM:-} ]]; then
    echo "<4>$*" >&2
  else
    echo "warning: $*" >&2
  fi
}

compose_exec() {
  (cd "$COMPOSE_DIR" && docker compose exec -T postgres "$@")
}

keep_newest() {
  local directory=$1 count=$2
  local -a files
  mapfile -t files < <(find "$directory" -maxdepth 1 -name '*.dump' -type f | sort)
  local excess=$(( ${#files[@]} - count ))
  if (( excess > 0 )); then
    rm -f -- "${files[@]:0:excess}"
  fi
}

umask 077
mkdir -p "$BACKUP_DIR/$kind"
chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/$kind"

exec 9> "$BACKUP_DIR/.lock"
flock -w 600 9

target="$BACKUP_DIR/$kind/$DATABASE-$(date -u +%Y-%m-%dT%H%M%SZ).dump"
partial=$(mktemp "$BACKUP_DIR/$kind/.partial.XXXXXX")
trap 'rm -f -- "$partial"' EXIT

compose_exec pg_dump -U postgres -d "$DATABASE" -Fc > "$partial"
compose_exec pg_restore --list < "$partial" > /dev/null
mv -- "$partial" "$target"
echo "backup written: $target ($(LC_ALL=C numfmt --to=iec --suffix=B "$(stat -c %s "$target")"))"

if [[ $kind == daily ]]; then
  keep_newest "$BACKUP_DIR/daily" "$BACKUP_KEEP_DAILY"

  mkdir -p "$BACKUP_DIR/weekly"
  chmod 700 "$BACKUP_DIR/weekly"
  weekly="$BACKUP_DIR/weekly/$DATABASE-$(date -u +%G-W%V).dump"
  if [[ ! -e $weekly ]]; then
    ln -- "$target" "$weekly"
  fi
  keep_newest "$BACKUP_DIR/weekly" "$BACKUP_KEEP_WEEKLY"
else
  keep_newest "$BACKUP_DIR/$kind" "$BACKUP_KEEP_PRE_UPDATE"
fi

free_mb=$(( $(df -Pk "$BACKUP_DIR" | awk 'NR == 2 { print $4 }') / 1024 ))
if (( free_mb < BACKUP_MIN_FREE_MB )); then
  warn "low disk space on $BACKUP_DIR: ${free_mb} MB free, threshold ${BACKUP_MIN_FREE_MB} MB"
fi
