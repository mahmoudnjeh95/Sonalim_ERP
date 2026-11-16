#!/usr/bin/env bash
# Back up the ERP database: dump, verify, apply retention, copy off-site.
#
#   tools/backup/backup.sh
#
# Settings: tools/backup/backup.env (see backup.env.example). Runbook: docs/backups.md.
# Exit codes: 0 done; 1 failed; 3 dump made but no off-site copy (BACKUP_REMOTE unset).
set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || die "another backup is already running"

partial=""
finish() {
  local rc=$?
  [[ -n $partial ]] && rm -f -- "$partial"
  if ((rc == 0)); then
    ping "$PING_URL" ""
  else
    log "FAILED (exit $rc)"
    ping "$PING_URL" "/fail"
  fi
}
trap finish EXIT

started=$SECONDS
ping "$PING_URL" "/start"
log "backup of database '$DB_NAME' into $BACKUP_DIR"

# Leftovers of an interrupted run (we hold the lock, so none is in progress).
find "$BACKUP_DIR" -maxdepth 1 -name '*.partial' -delete

# Enough room for the new dump: twice the last one, and at least MIN_FREE_MB.
last=$(find "$BACKUP_DIR" -maxdepth 1 -type f -regextype posix-extended -regex ".*/${DUMP_RE:1:-1}" -printf '%T@ %s\n' | sort -n | tail -1 | cut -d' ' -f2)
need_kb=$((MIN_FREE_MB * 1024))
if [[ -n $last ]] && ((last / 1024 * 2 > need_kb)); then need_kb=$((last / 1024 * 2)); fi
free_kb=$(df -Pk "$BACKUP_DIR" | awk 'NR == 2 { print $4 }')
((free_kb >= need_kb)) || die "not enough disk space in $BACKUP_DIR: $((free_kb / 1024)) MB free, need $((need_kb / 1024)) MB"

name="${BACKUP_PREFIX}_$(date -u +%Y%m%dT%H%M%SZ).dump"
partial="$BACKUP_DIR/$name.partial"

pg pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom --compress=6 > "$partial"
[[ -s $partial ]] || die "pg_dump wrote an empty file"

# A dump is only kept if pg_restore can read its table of contents back.
tables=$(toc_table_count < "$partial")
((tables > 0)) || die "dump has no tables in its table of contents"

mv -- "$partial" "$BACKUP_DIR/$name"
partial=""
(cd "$BACKUP_DIR" && sha256sum -- "$name" > "$name.sha256")
size=$(stat -c %s "$BACKUP_DIR/$name")
log "dump $name: $(human_size "$size"), $tables tables, $((SECONDS - started))s"

# Local retention.
mapfile -t old < <(ls -1 "$BACKUP_DIR" | python3 "$SCRIPT_DIR/retention.py" --prefix "$BACKUP_PREFIX" \
  --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY")
for f in "${old[@]}"; do
  rm -f -- "$BACKUP_DIR/$f" "$BACKUP_DIR/$f.sha256"
done
# shellcheck disable=SC2010 # names follow a fixed pattern
log "local retention: removed ${#old[@]}, kept $(ls -1 "$BACKUP_DIR" | grep -cE "$DUMP_RE")"

# Off-site copy.
if [[ -z $BACKUP_REMOTE ]]; then
  if [[ $ALLOW_LOCAL_ONLY == 1 ]]; then
    log "WARNING no off-site copy (BACKUP_REMOTE is empty, ALLOW_LOCAL_ONLY=1)"
    exit 0
  fi
  log "ERROR no off-site copy: set BACKUP_REMOTE in $BACKUP_ENV (or ALLOW_LOCAL_ONLY=1)"
  exit 3
fi

rtype=$(remote_type)
[[ -n $rtype ]] || die "rclone remote '${BACKUP_REMOTE%%:*}' is not configured (rclone config)"
if [[ $rtype != crypt ]]; then
  log "WARNING off-site remote is '$rtype', not 'crypt': the dumps (payroll, customers) are stored unencrypted"
fi

# Copy every kept dump the remote does not have yet, so a missed night catches up.
filters=(--filter '- *.partial' --filter "+ /${BACKUP_PREFIX}_*.dump" --filter "+ /${BACKUP_PREFIX}_*.dump.sha256" --filter '- *')
"${RCLONE[@]}" copy "$BACKUP_DIR" "$BACKUP_REMOTE" "${filters[@]}" --retries 5 --low-level-retries 20
if [[ $rtype == crypt ]]; then
  "${RCLONE[@]}" cryptcheck "$BACKUP_DIR" "$BACKUP_REMOTE" --one-way "${filters[@]}"
else
  "${RCLONE[@]}" check "$BACKUP_DIR" "$BACKUP_REMOTE" --one-way "${filters[@]}"
fi
log "off-site copy verified at $BACKUP_REMOTE"

# Off-site retention.
mapfile -t old < <("${RCLONE[@]}" lsf --files-only "$BACKUP_REMOTE" | python3 "$SCRIPT_DIR/retention.py" \
  --prefix "$BACKUP_PREFIX" --keep-daily "$REMOTE_KEEP_DAILY" --keep-weekly "$REMOTE_KEEP_WEEKLY" \
  --keep-monthly "$REMOTE_KEEP_MONTHLY")
for f in "${old[@]}"; do
  "${RCLONE[@]}" deletefile "$BACKUP_REMOTE/$f"
  "${RCLONE[@]}" deletefile "$BACKUP_REMOTE/$f.sha256" 2>/dev/null || true
done
log "off-site retention: removed ${#old[@]}"
log "done in $((SECONDS - started))s"
