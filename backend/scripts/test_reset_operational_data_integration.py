"""The go-live reset wipes operational data, keeps master data, and cannot drift from the schema."""
from __future__ import annotations

import pytest

from scripts import reset_operational_data as reset


def _tenant(db) -> str:
    row = db.execute("SELECT tenant_id FROM core.users LIMIT 1").fetchone()
    return row[0] if row else "demo"


def test_every_live_table_is_classified(db):
    """A migration that adds a table must decide whether the reset keeps or wipes it."""
    try:
        reset.check_ready(db)
    except reset.ResetError as error:
        pytest.fail(str(error))


def test_purge_wipes_operational_data_and_keeps_master_data(db):
    tenant = _tenant(db)
    live = reset.live_tables(db)
    kept = [t for t in reset.KEPT_TABLES if t in live]
    before = {t: reset._count(db, t) for t in kept}
    suppliers = db.execute("SELECT count(*) FROM core.partners WHERE kind <> 'customer'").fetchone()[0]

    reset.purge(db, tenant)

    for table in reset.PURGE_TABLES:
        if table in live:
            assert reset._count(db, table) == 0, f"{table} still has rows"
    for table in kept:
        assert reset._count(db, table) == before[table], f"{table} is master data and must not change"
    assert db.execute("SELECT count(*) FROM core.partners WHERE kind = 'customer'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM core.partners WHERE kind <> 'customer'").fetchone()[0] == suppliers
    assert db.execute(
        "SELECT count(*) FROM warehouse.stock_items "
        "WHERE quantity_on_hand <> 0 OR quantity_reserved <> 0 OR quantity_in_production <> 0"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT count(*) FROM core.sequences WHERE name = ANY(%s) AND next_value <> 0", (reset.RESET_SEQUENCES,)
    ).fetchone()[0] == 0


def test_purge_can_keep_customers(db):
    tenant = _tenant(db)
    customers = db.execute("SELECT count(*) FROM core.partners WHERE kind = 'customer'").fetchone()[0]

    reset.purge(db, tenant, keep_customers=True)

    assert db.execute("SELECT count(*) FROM core.partners WHERE kind = 'customer'").fetchone()[0] == customers


def test_unclassified_table_stops_the_reset(db):
    db.execute("CREATE TABLE core.reset_probe_unclassified (id INT)")
    with pytest.raises(reset.ResetError, match="reset_probe_unclassified"):
        reset.purge(db, _tenant(db))
