# Go-live data reset

Goal: start real use with master data only (users, roles, products, warehouse locations,
suppliers, machines, molds, BOMs, configuration) and keep the current test data
available so development testing can continue.

Git branches do not carry data, so there is **one code line** and **two databases**:

| | Database | Holds |
|---|---|---|
| Real use | server `erp` (after the reset) | master data only, stock at 0 |
| Dev testing | the backup dump, or your local `erp` | everything as it is today |

Bug fixes found in real use: fix on the dev branch, merge to `main`, deploy. Migrations
run at startup and keep the data.

## What the reset does

`backend/scripts/reset_operational_data.py` (read its docstring for the full list).

- **Wipes:** OF and OFR, legacy Daily/Conditionnement reports, per-shift reports and all
  their sub-tables, QC reports and NCs, stock moves and lots, purchasing, sales, CRM,
  finance, HR, audit log, event outbox, AI assistant history, customers.
- **Zeroes:** every quantity in `warehouse.stock_items` (rows stay) and the OF-/OFR-/NC-
  counters, so the first real order is `OF-1`.
- **Keeps:** users (including `demo@sonalim-erp.local`), roles, permissions, products,
  suppliers, warehouse locations, machines, work centers, molds, recipes, BOMs, team rotations,
  shift windows, report options, waste types.

Safety: one transaction, no `CASCADE`, refuses to run if any table is not classified in
the script, refuses to run for real unless `--confirm-database` matches the database it is
connected to. `--dry-run` does everything and rolls back.

## On the server (Docker)

Run from the folder that holds `compose.yaml`.

```bash
# 1. Backup -- this is your dev-data copy. Keep it OUTSIDE the repo.
docker compose exec -T postgres pg_dump -U erp -Fc erp > sonalim_dev_2026-09-21.dump
ls -lh sonalim_dev_2026-09-21.dump        # must not be empty

# 2. Preview (changes nothing)
docker compose exec -T app python -m scripts.reset_operational_data --dry-run
```

If step 2 says `No module named scripts.reset_operational_data`, the running image predates
this script. Either rebuild/pull the image, or feed the file in directly:

```bash
docker compose exec -T app python - --dry-run < backend/scripts/reset_operational_data.py
```

```bash
# 3. Real run, with the app quiet so nobody writes during the wipe
docker compose stop web app worker
docker compose run --rm --no-deps app python -m scripts.reset_operational_data --confirm-database erp
docker compose start app worker web
```

Then log in and check: Production board, OF list and Stock pages open empty without errors,
stock shows 0, and creating an OF gives `OF-1`.

### Getting the dev data back later

```bash
docker compose exec -T postgres createdb -U erp erp_dev
docker compose exec -T postgres pg_restore -U erp -d erp_dev < sonalim_dev_2026-09-21.dump
```

Point a second app at it with `DATABASE_URL=postgresql://erp:<password>@postgres:5432/erp_dev`
(separate compose project, or locally in `backend/.env`).

## Locally (run-app.bat)

Leave local `erp` as it is: it is already the dev-data database (`backend/.env` points at it).
Do **not** run the reset locally unless you first take a pgAdmin backup of `erp`
(right-click the database, Backup, format Custom). The local `erp` user cannot
`CREATE DATABASE`, so a clone needs the `postgres` superuser in pgAdmin.

To rehearse the reset locally without changing anything: `python -m scripts.reset_operational_data --dry-run`
from `backend/` with the venv active.

## When someone adds a table later

`test_every_live_table_is_classified` fails until the new table is added to `PURGE_TABLES`,
`EDITED_TABLES` or `KEPT_TABLES` in the script.
