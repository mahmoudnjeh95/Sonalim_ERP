# Backups and restore

Runbook for the live server. Design: `docs/superpowers/specs/2026-11-16-backups-design.md`.
Scripts: `tools/backup/` (a deploy copies them next to `compose.yaml` on the server).

## What is saved, and what you must keep yourself

The nightly dump of the `erp` database holds **all** business data, including photos,
avatars, scanned sheets and attachments (they are stored in the database). Nothing else on
the server needs a backup to rebuild the app.

Two things are **not** in the dump. Keep a copy of each in a password manager, not on the
server and not in the backup bucket:

1. the server `.env` (database, RabbitMQ and API passwords);
2. `~/.config/rclone/rclone.conf`: the off-site credentials **and the encryption
   passwords**. Without these passwords the off-site dumps cannot be decrypted by anyone.

## How it runs

| When | What | Result |
|---|---|---|
| Every night 02:17 | `backup.sh` | `erp_<UTC time>.dump` + `.sha256` in `~/sonalim-erp-backups`, copied encrypted off-site and verified |
| 1st of the month 04:43 | `restore.sh --drill --from-remote` | newest off-site dump restored into a scratch database, checked, dropped; one line in `restore-drills.log` |

Kept, both on the server and off-site: the newest dump of each of the last **14 days,
8 weeks and 12 months**. Everything is logged to `~/sonalim-erp-backups/backup.log`.

## Pre-deploy dumps

Every deploy (each push to `main`) first runs `pg_dump` of the live database into
`~/sonalim-erp-backups/pre-deploy_<UTC time>.dump`, before the new app starts and applies
its migrations. If the dump fails or is empty, the deploy stops. The newest one per day is
kept for the last 10 days with a deploy. They stay on the server only (not off-site, no
`.sha256`) and are restored like any other dump:

```bash
bash tools/backup/restore.sh --into-live --confirm-database erp ~/sonalim-erp-backups/pre-deploy_<time>.dump
```

## One-time setup on the server

Run as `debian`, from the compose folder, after a deploy has copied `tools/backup/`:

```bash
cd /home/debian/Sonalim_erp/Erpsonalim
ls tools/backup/backup.sh                       # present after the first deploy of this change
sudo apt install -y rclone
mkdir -p -m 700 ~/sonalim-erp-backups
cp tools/backup/backup.env.example tools/backup/backup.env && chmod 600 tools/backup/backup.env
```

### 1. Off-site storage, encrypted

Pick any storage rclone supports, away from this VPS provider if possible: Backblaze B2
or another S3 bucket (simplest on a server: an access key, no browser login), Google
Drive, or SFTP to another machine. Then wrap it in a `crypt` remote so the provider only
ever sees encrypted files. Example with Backblaze B2 (create a private bucket and an
application key restricted to it first):

```bash
rclone config create offsite b2 account <keyID> key <applicationKey>
rclone config create offsite-crypt crypt remote offsite:<bucket>/sonalim-erp \
  password '<long random passphrase 1>' password2 '<long random passphrase 2>' --obscure
rclone lsd offsite:                              # must list the bucket
chmod 600 ~/.config/rclone/rclone.conf
history -c                                       # the passphrases were typed on the command line
```

**Now save `rclone.conf` and both passphrases in the password manager.** The two
passphrases alone are enough to decrypt the dumps from a freshly written config. For Google Drive
the `rclone config` wizard needs a browser: run `rclone authorize "drive"` on a desktop and
paste the token into the server (`rclone config`, answer "n" to auto config).

### 2. Settings

Edit `tools/backup/backup.env`: `BACKUP_REMOTE=offsite-crypt:` (as created above). For
alerts, create two free checks at healthchecks.io (one daily, one monthly, grace a few
hours) and put their URLs in `PING_URL` and `DRILL_PING_URL`. They email you when a run
fails **or does not run at all**.

### 3. First backup and first restore (this is WP-0.2's "done when")

```bash
bash tools/backup/backup.sh                      # ends with "done in Ns"
bash tools/backup/restore.sh --drill --from-remote   # ends with "DRILL PASSED"
cat ~/sonalim-erp-backups/restore-drills.log
```

The drill downloads the newest off-site dump, checks its checksum, restores it into
`erp_restore_drill`, checks the table count matches the dump and that migrations, users
and products are there, prints row counts, and drops the scratch database. The live
database is not touched. Compare the printed row counts with what you know is in the app.

### 4. Schedule it

```bash
crontab -e      # paste the lines from tools/backup/crontab.example
sudo tee /etc/logrotate.d/sonalim-erp-backup > /dev/null <<'EOF'
/home/debian/sonalim-erp-backups/backup.log {
  monthly
  rotate 12
  compress
  missingok
  notifempty
}
EOF
```

The next morning: `tail ~/sonalim-erp-backups/backup.log` and `ls ~/sonalim-erp-backups`.

## Daily checks

- healthchecks.io stays green (or read `backup.log`: each night ends with `done in`).
- `rclone ls offsite-crypt:` lists the off-site dumps (decrypted names).

`backup.sh` exit codes: 0 done; 1 failed (reason on the `ERROR` line); 3 dump made but no
off-site copy because `BACKUP_REMOTE` is empty.

## Restoring

Every restore first verifies the `.sha256` and restores into a separate database; the
live database is only swapped once that restore has passed its checks.

### Wrong data in the live database (bad import, mistaken deletion, corruption)

```bash
cd /home/debian/Sonalim_erp/Erpsonalim
ls ~/sonalim-erp-backups                         # pick the dump from before the problem
bash tools/backup/restore.sh --into-live --confirm-database erp ~/sonalim-erp-backups/erp_<time>.dump
# or the newest off-site copy:
bash tools/backup/restore.sh --into-live --confirm-database erp --from-remote
```

It stops `web app worker`, renames the current database to `erp_replaced_<time>`
(kept, not deleted), renames the restored one to `erp`, and starts the services. The
app applies any migration newer than the dump at start-up. **Everything entered after the
dump's time is lost** from `erp` (it is still in `erp_replaced_<time>`). Check the app,
then free the space with the `DROP DATABASE` command the script prints.

### Getting back a few rows only

Restore into a scratch database and keep it, then copy what is needed:

```bash
bash tools/backup/restore.sh --drill --keep ~/sonalim-erp-backups/erp_<time>.dump
docker compose exec -T postgres psql -U erp -d erp_restore_drill   # inspect, export
docker compose exec -T postgres psql -U erp -d postgres -c 'DROP DATABASE erp_restore_drill'
```

### The server is lost

On a new VPS (Docker installed, user `debian`):

1. Recreate `/home/debian/Sonalim_erp/Erpsonalim` with `compose.yaml` and `tools/backup/`
   from the repo, and the `.env` from the password manager.
2. `sudo apt install -y rclone`, put `rclone.conf` from the password manager in
   `~/.config/rclone/`, `rclone ls offsite-crypt:` must list the dumps.
3. Create `tools/backup/backup.env` as above.
4. Log in to ghcr.io with a GitHub personal token that can read the repo's packages
   (`echo <token> | docker login ghcr.io -u <github user> --password-stdin`) and start
   only the database:
   `docker compose up -d postgres`.
5. `bash tools/backup/restore.sh --into-live --confirm-database erp --from-remote`
6. `docker compose up -d`, check the app, then set up cron again (step 4 above) and
   point the deploy secrets (`SERVER_HOST`, ...) at the new server.

## Limits

- Up to one day of data can be lost (nightly dump). For less, add WAL archiving
  (point-in-time recovery); not done yet.
- Monitoring is the healthchecks ping only; wider alerting is WP-0.6.
- Dumps stay on the same disk as the database too; the off-site copy is the real backup.
