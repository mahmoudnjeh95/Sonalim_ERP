# shellcheck shell=bash disable=SC2034
# Shared settings and helpers for backup.sh and restore.sh. Sourced, not run.
# Settings come from the environment, then tools/backup/backup.env (see backup.env.example).

BACKUP_ENV=${BACKUP_ENV:-$SCRIPT_DIR/backup.env}
if [[ -f $BACKUP_ENV ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$BACKUP_ENV"
  set +a
fi

# The folder that holds compose.yaml. On the server the scripts live in
# <compose dir>/tools/backup, so it is two levels up by default.
COMPOSE_DIR=${COMPOSE_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}
COMPOSE_FILE_PATH=${COMPOSE_FILE_PATH:-$COMPOSE_DIR/compose.yaml}
DB_NAME=${DB_NAME:-erp}
DB_USER=${DB_USER:-erp}
BACKUP_DIR=${BACKUP_DIR:-$HOME/sonalim-erp-backups}
BACKUP_PREFIX=${BACKUP_PREFIX:-$DB_NAME}
KEEP_DAILY=${KEEP_DAILY:-14}
KEEP_WEEKLY=${KEEP_WEEKLY:-8}
KEEP_MONTHLY=${KEEP_MONTHLY:-12}
REMOTE_KEEP_DAILY=${REMOTE_KEEP_DAILY:-$KEEP_DAILY}
REMOTE_KEEP_WEEKLY=${REMOTE_KEEP_WEEKLY:-$KEEP_WEEKLY}
REMOTE_KEEP_MONTHLY=${REMOTE_KEEP_MONTHLY:-$KEEP_MONTHLY}
BACKUP_REMOTE=${BACKUP_REMOTE:-}
ALLOW_LOCAL_ONLY=${ALLOW_LOCAL_ONLY:-0}
RCLONE_CONFIG=${RCLONE_CONFIG:-}
PING_URL=${PING_URL:-}
DRILL_PING_URL=${DRILL_PING_URL:-}
MIN_FREE_MB=${MIN_FREE_MB:-1024}
# Services stopped while the live database is swapped (restore.sh --into-live).
STOP_SERVICES=${STOP_SERVICES-web app worker}

# Prefix that runs Postgres client tools next to the server, so the dump is made by the
# server's own pg_dump version. Set PG_EXEC= (empty) to use local tools and PG* variables.
if [[ -z ${PG_EXEC+set} ]]; then
  PG_EXEC="docker compose -f $COMPOSE_FILE_PATH exec -T postgres"
fi
read -r -a _PG_EXEC <<< "$PG_EXEC"
COMPOSE=(docker compose -f "$COMPOSE_FILE_PATH")

RCLONE=(rclone)
if [[ -n $RCLONE_CONFIG ]]; then
  RCLONE+=(--config "$RCLONE_CONFIG")
fi

DUMP_RE="^${BACKUP_PREFIX}_[0-9]{8}T[0-9]{6}Z\.dump$"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR $*"; exit 1; }

# Run a Postgres client tool (pg_dump, pg_restore, psql, createdb) next to the server.
pg() { "${_PG_EXEC[@]}" "$@"; }

# psql returning bare values; stops on the first error.
sql() { pg psql -U "$DB_USER" -X -v ON_ERROR_STOP=1 -At "$@"; }

# Ping a healthchecks.io-style monitor: ping <url> "" | /start | /fail. Never fails the run.
ping() {
  local url=$1 suffix=$2
  [[ -n $url ]] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${url}${suffix}" || log "WARNING monitor ping ${suffix:-/ok} failed"
}

# Type of the rclone remote holding BACKUP_REMOTE ("crypt", "b2", ...), or "local".
remote_type() {
  if [[ $BACKUP_REMOTE != *:* ]]; then
    echo local
    return
  fi
  local name=${BACKUP_REMOTE%%:*}
  "${RCLONE[@]}" listremotes --long | awk -v n="$name:" '$1 == n { print $2 }'
}

# Number of tables in a dump's table of contents (dump read on stdin).
toc_table_count() {
  pg pg_restore --list | grep -E '^[0-9]+; [0-9]+ [0-9]+ TABLE ' | grep -vc ' TABLE DATA ' || true
}

human_size() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "${1}B"; }
