#!/usr/bin/env bash
# Restore an ERP database dump.
#
#   restore.sh --drill [DUMP]                 restore into a scratch database, check it, drop it
#   restore.sh --drill --from-remote          same, from the newest off-site copy
#   restore.sh --into-live --confirm-database erp [DUMP | --from-remote]
#                                             replace the live database (old one is kept, renamed)
#
# DUMP defaults to the newest dump in BACKUP_DIR. Runbook: docs/backups.md.
set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

mode="" from_remote=0 confirm="" keep=0 dump=""
while (($#)); do
  case $1 in
    --drill) mode=drill ;;
    --into-live) mode=live ;;
    --from-remote) from_remote=1 ;;
    --confirm-database) confirm=${2:-}; shift ;;
    --keep) keep=1 ;;  # drill: leave the scratch database for inspection
    -h | --help) usage ;;
    -*) die "unknown option $1" ;;
    *) dump=$1 ;;
  esac
  shift
done
[[ -n $mode ]] || usage
[[ -z $dump || $from_remote == 0 ]] || die "give either a dump file or --from-remote, not both"
if [[ $mode == live && $confirm != "$DB_NAME" ]]; then
  die "--into-live replaces database '$DB_NAME': repeat its name with --confirm-database $DB_NAME"
fi

started=$SECONDS
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="${DB_NAME}_restore_drill"
[[ $mode == live ]] && target="${DB_NAME}_incoming"
workdir=""
ping_url=""
[[ $mode == drill ]] && ping_url=$DRILL_PING_URL

finish() {
  local rc=$?
  [[ -n $workdir ]] && rm -rf -- "$workdir"
  if ((rc != 0)); then
    log "RESTORE FAILED (exit $rc)"
    ping "$ping_url" "/fail"
  fi
}
trap finish EXIT
ping "$ping_url" "/start"

# --- pick the dump -------------------------------------------------------------------
source_label=local
if ((from_remote)); then
  [[ -n $BACKUP_REMOTE ]] || die "--from-remote needs BACKUP_REMOTE"
  name=$("${RCLONE[@]}" lsf --files-only "$BACKUP_REMOTE" | grep -E "$DUMP_RE" | sort | tail -1 || true)
  [[ -n $name ]] || die "no dump found at $BACKUP_REMOTE"
  mkdir -p "$BACKUP_DIR"
  workdir=$(mktemp -d "$BACKUP_DIR/.restore-XXXXXX")
  log "downloading $name from $BACKUP_REMOTE"
  "${RCLONE[@]}" copyto "$BACKUP_REMOTE/$name" "$workdir/$name"
  "${RCLONE[@]}" copyto "$BACKUP_REMOTE/$name.sha256" "$workdir/$name.sha256" \
    || die "no checksum file $name.sha256 at $BACKUP_REMOTE"
  dump="$workdir/$name"
  source_label="off-site ($BACKUP_REMOTE)"
elif [[ -z $dump ]]; then
  # shellcheck disable=SC2010 # names follow a fixed pattern
  name=$(ls -1 "$BACKUP_DIR" 2>/dev/null | grep -E "$DUMP_RE" | sort | tail -1 || true)
  [[ -n $name ]] || die "no dump in $BACKUP_DIR"
  dump="$BACKUP_DIR/$name"
fi
[[ -f $dump ]] || die "no such file: $dump"
name=$(basename -- "$dump")

if [[ -f $dump.sha256 ]]; then
  (cd "$(dirname -- "$dump")" && sha256sum --quiet -c -- "$name.sha256") || die "checksum mismatch for $name"
  log "checksum ok"
else
  log "WARNING no $name.sha256 beside the dump: checksum not verified"
fi

expected=$(toc_table_count < "$dump")
((expected > 0)) || die "$name: no tables in its table of contents (not a custom-format dump?)"
log "restoring $name ($(human_size "$(stat -c %s "$dump")"), $expected tables, from $source_label) into '$target'"

# --- restore into a database of its own ----------------------------------------------
sql -d postgres -c "SET client_min_messages = warning" -c "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)" > /dev/null
sql -d postgres -c "CREATE DATABASE \"$target\" OWNER \"$DB_USER\"" > /dev/null
pg pg_restore -U "$DB_USER" -d "$target" --no-owner --exit-on-error < "$dump"

# --- check it ----------------------------------------------------------------------
restored=$(sql -d "$target" -c "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')")
[[ $restored == "$expected" ]] || die "restored $restored tables, the dump lists $expected"
migrations=$(sql -d "$target" -c "SELECT count(*) FROM core.module_migrations")
((migrations > 0)) || die "core.module_migrations is empty in the restored database"
for t in core.users core.products; do
  n=$(sql -d "$target" -c "SELECT count(*) FROM $t")
  ((n > 0)) || die "$t is empty in the restored database"
done

# Row counts of the main tables, for the record (missing tables are skipped).
counts=$(sql -d "$target" -F ' ' -c "
  SELECT t, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %s', t), false, true, '')))[1]::text
  FROM unnest(ARRAY['core.companies', 'core.users', 'core.products', 'core.partners',
                    'production.shift_reports', 'warehouse.stock_moves', 'warehouse.cost_layers',
                    'finance.journal_entries', 'finance.invoices', 'hr.employees',
                    'payroll.runs', 'events.outbox']) AS t
  WHERE to_regclass(t) IS NOT NULL")
newest=$(sql -d "$target" -c "SELECT coalesce(max(created_at)::text, 'none') FROM events.outbox")
log "checks passed: $restored tables, $migrations migrations applied, newest event $newest"
while read -r t n; do
  [[ -n $t ]] && log "  $t: $n rows"
done <<< "$counts"

# --- drill: record and drop ----------------------------------------------------------
if [[ $mode == drill ]]; then
  if ((keep)); then
    log "scratch database '$target' kept (--keep); drop it when done"
  else
    sql -d postgres -c "DROP DATABASE \"$target\"" > /dev/null
  fi
  mkdir -p "$BACKUP_DIR"
  printf '%s PASSED %s from %s: %s tables, %s migrations, newest event %s, %ss\n' \
    "$stamp" "$name" "$source_label" "$restored" "$migrations" "$newest" "$((SECONDS - started))" \
    >> "$BACKUP_DIR/restore-drills.log"
  log "DRILL PASSED in $((SECONDS - started))s (recorded in $BACKUP_DIR/restore-drills.log)"
  ping "$ping_url" ""
  exit 0
fi

# --- live: swap the restored database in -------------------------------------------
old="${DB_NAME}_replaced_${stamp}"
read -r -a services <<< "$STOP_SERVICES"
if ((${#services[@]})); then
  log "stopping ${services[*]}"
  "${COMPOSE[@]}" stop "${services[@]}"
fi
if [[ $(sql -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = '$DB_NAME'") == 1 ]]; then
  sql -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid()" > /dev/null
  sql -d postgres -c "ALTER DATABASE \"$DB_NAME\" RENAME TO \"$old\"" > /dev/null
  kept_old=1
else
  kept_old=0  # new server: nothing to set aside
fi
sql -d postgres -c "ALTER DATABASE \"$target\" RENAME TO \"$DB_NAME\"" > /dev/null
if ((kept_old)); then
  log "'$DB_NAME' is now the restored $name; the previous database is kept as '$old'"
else
  log "'$DB_NAME' is now the restored $name"
fi
if ((${#services[@]})); then
  # app runs any migration newer than the dump on start (AUTO_MIGRATE).
  "${COMPOSE[@]}" start "${services[@]}"
  log "started ${services[*]}"
fi
log "RESTORE DONE in $((SECONDS - started))s"
if ((kept_old)); then
  log "check the app, then free the space: docker compose exec -T postgres psql -U $DB_USER -d postgres -c 'DROP DATABASE \"$old\"'"
fi
