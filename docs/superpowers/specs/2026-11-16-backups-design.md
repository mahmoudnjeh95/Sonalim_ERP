# Backups (WP-0.2) — design

Roadmap: `docs/ROADMAP.md`, WP-0.2. *Done when* a restore has been run once from a backup.

## What has to be saved

Everything the business owns lives in the `erp` Postgres database, including files: user
avatars, maintenance photos, scanned shift sheets and purchase/delivery attachments are
`BYTEA` columns. The app and worker containers have no volumes. So one `pg_dump` of `erp`
is a complete backup of the business data.

Not in the dump, and kept by hand (password manager, not the backup bucket):

- the server `.env` (database, RabbitMQ and API passwords);
- the rclone config, which holds the off-site credentials and the encryption key.

Not needed: RabbitMQ (the outbox is in Postgres; unsent rows re-dispatch after a restore,
and consumers are idempotent on `event_id`), Redis (rate limits), Grafana/Prometheus
(rebuildable). No database roles other than `erp` exist, so no `pg_dumpall --globals-only`.
The one extension (`btree_gist`) is in the dump.

## Shape

Host-side scripts in `tools/backup/`, run by the `debian` user's cron on the VPS. They talk
to Postgres through `docker compose exec -T postgres`, so the dump is made by the same
`pg_dump` major version as the server (18) and no Postgres client is needed on the host.
`PG_EXEC` overrides that prefix (empty = local `pg_dump`/`psql`) for testing.

Chosen over a backup container in `compose.yaml`: the deploy job only restarts
`app worker web ocr`, so a new service would not be started by a deploy anyway; a sidecar
would also need rclone and the off-site credentials inside a container. Cron on the host is
simpler to see and to fix.

| File | Job |
|---|---|
| `backup.sh` | lock, check free disk, `pg_dump -Fc` to a `.partial` file, verify with `pg_restore --list`, rename, write `.sha256`, apply retention, copy off-site, apply retention off-site, ping monitor |
| `retention.py` | decides which dumps to delete (grandfather-father-son); stdlib only; unit-tested |
| `restore.sh` | `--drill`: restore into a scratch database, check it, drop it. `--into-live`: safety dump of the current database, stop app/worker/web, recreate `erp`, restore, start |
| `backup.env.example` | settings, copied to `backup.env` on the server (not in git) |
| `crontab.example` | nightly backup, monthly drill |

## Decisions

- **Format:** custom (`-Fc`), compressed, restorable table by table. Name
  `erp_YYYYMMDDTHHMMSSZ.dump` (UTC), plus a `.sha256` beside it. Files `0600`, dir `0700`.
- **Retention (default):** the newest dump of each of the last 14 days, 8 ISO weeks and
  12 months. Same policy local and off-site (overridable). Retention never deletes the
  newest dump and never touches files that do not match the name pattern.
- **Off-site:** rclone, so the destination is the user's choice (Backblaze B2, S3, Google
  Drive, SFTP to another machine). The dump holds payroll and customer data, so the runbook
  sets up an rclone `crypt` remote; `backup.sh` warns when the remote is not `crypt`.
  `rclone check` verifies the upload. Without a remote the run exits with code 3 (backup
  incomplete) unless `ALLOW_LOCAL_ONLY=1`.
- **Monitoring:** optional `PING_URL` (healthchecks.io-style): `<url>/start`, `<url>` on
  success, `<url>/fail` on failure. A missed ping alerts even when cron itself is dead.
  Full alerting is WP-0.6.
- **Drill:** restores into `erp_restore_drill`, compares the table count with the dump's
  table of contents, checks `core.module_migrations` and core tables are non-empty, prints
  row counts for key tables and the newest `events.outbox.created_at`, then drops the
  scratch database. `--from-remote` pulls the newest off-site copy first, which proves the
  off-site copy is usable, not just present.
- **Live restore safety:** refuses unless `--confirm-database <name>` matches; always takes
  a safety dump of the current database first; stops `web app worker` during the restore;
  pending migrations run at app start (`AUTO_MIGRATE`), so a dump older than the code is
  fine.
- **Deploy:** `deploy.yml` copies `tools/backup/` next to `compose.yaml`, so the server
  always runs the reviewed scripts. Installing cron and `backup.env` is a one-time manual
  step (runbook).

## Out of scope

Point-in-time recovery (WAL archiving): a nightly dump loses up to a day; revisit if the
business needs less. Alerting beyond the ping (WP-0.6).
