"""Integration tests for the warehouse KPI overview, against a real database.

The overview is what the stock manager reads first, so each figure is pinned
to the movements that produce it: what is on hand and worth, how fast it is
used, what sits blocked or dormant, how much the books had to be corrected,
and which lots are about to expire.
"""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from modules.warehouse.api.analytics_service import WarehouseAnalyticsService

TENANT = "integration-test-warehouse-analytics"
TODAY = datetime.date(2026, 9, 24)
D = datetime.date


def _ts(day: datetime.date, hour: int = 10) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour=hour))


@pytest.fixture
def env(db):
    kg, piece = str(ULID()), str(ULID())
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (kg, TENANT))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'piece', 'Pièce', 'unit')", (piece, TENANT))

    semoule, carton, film = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, purchase_price, stock_alert_threshold) VALUES (%s, %s, 'SEM', 'Semoule', %s, 250, 5000)",
        (semoule, TENANT, kg),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, purchase_price, stock_alert_threshold) VALUES (%s, %s, 'CAR', 'Carton 24', %s, 0, 100)",
        (carton, TENANT, piece),
    )
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, purchase_price) VALUES (%s, %s, 'FIL', 'Film 500g', %s, 1200)",
        (film, TENANT, kg),
    )

    store, quarantine = str(ULID()), str(ULID())
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'MP', 'Matières premières')", (store, TENANT))
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name, is_blocked) VALUES (%s, %s, 'QUAR', 'Quarantaine', TRUE)",
        (quarantine, TENANT),
    )

    def stock(product, location, on_hand, reserved=0, in_production=0):
        db.execute(
            """
            INSERT INTO warehouse.stock_items (tenant_id, location_id, product_id, quantity_on_hand, quantity_reserved, quantity_in_production)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (TENANT, location, product, on_hand, reserved, in_production),
        )

    def move(product, location, quantity, move_type, when, reason=None):
        db.execute(
            """
            INSERT INTO warehouse.stock_moves (id, tenant_id, location_id, product_id, quantity, move_type, reference, reason, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'test', %s, %s)
            """,
            (str(ULID()), TENANT, location, product, quantity, move_type, reason, _ts(when)),
        )

    # Semoule: 3,000 kg on hand, 300 kg/day consumed over the last 30 days -> 10 days of cover.
    stock(semoule, store, 3000, reserved=200)
    for offset in range(1, 31):
        move(semoule, store, 300, "production_consumption", TODAY - datetime.timedelta(days=offset))
    move(semoule, store, 9000, "receipt", TODAY - datetime.timedelta(days=20))
    move(semoule, store, -50, "adjustment", TODAY - datetime.timedelta(days=3), reason="count")
    # Film: 40 kg in quarantine, nothing moved for 90 days -> blocked and dormant.
    stock(film, quarantine, 40)
    move(film, quarantine, 40, "transfer_in", TODAY - datetime.timedelta(days=90))
    # Carton: no cost, below threshold, no consumption in window -> idle, unvalued.
    stock(carton, store, 60)
    move(carton, store, 60, "receipt", TODAY - datetime.timedelta(days=200))

    lot_soon, lot_expired, lot_far = (str(ULID()) for _ in range(3))
    db.execute(
        "INSERT INTO warehouse.lots (id, tenant_id, product_id, lot_number, expiry_date) VALUES (%s, %s, %s, 'L-SOON', %s)",
        (lot_soon, TENANT, film, TODAY + datetime.timedelta(days=10)),
    )
    db.execute(
        "INSERT INTO warehouse.lots (id, tenant_id, product_id, lot_number, expiry_date) VALUES (%s, %s, %s, 'L-PAST', %s)",
        (lot_expired, TENANT, film, TODAY - datetime.timedelta(days=2)),
    )
    db.execute(
        "INSERT INTO warehouse.lots (id, tenant_id, product_id, lot_number, expiry_date) VALUES (%s, %s, %s, 'L-FAR', %s)",
        (lot_far, TENANT, film, TODAY + datetime.timedelta(days=200)),
    )
    db.execute(
        "INSERT INTO warehouse.lot_stock (tenant_id, lot_id, location_id, quantity_on_hand) VALUES (%s, %s, %s, 15)",
        (TENANT, lot_soon, quarantine),
    )
    return {"semoule": semoule, "carton": carton, "film": film, "kg": kg, "piece": piece, "store": store}


def _overview(db, **overrides):
    params = dict(
        tenant_id=TENANT,
        date_from=TODAY - datetime.timedelta(days=29),
        date_to=TODAY,
        consumption_window_days=30,
        dormant_after_days=60,
        today=TODAY,
    )
    params.update(overrides)
    return WarehouseAnalyticsService(db).overview(**params)


def _row(overview, product_id):
    return next(r for r in overview["products"] if r["product_id"] == product_id)


def test_days_of_cover_comes_from_the_consumption_window(db, env):
    semoule = _row(_overview(db), env["semoule"])
    assert semoule["on_hand"] == 3000
    assert semoule["avg_daily_consumption"] == pytest.approx(300)
    assert semoule["days_of_cover"] == pytest.approx(10)
    assert semoule["coverage_status"] == "warning"


def test_stock_value_sums_only_products_with_a_cost(db, env):
    overview = _overview(db)
    # Semoule 3000 kg x 250 + film 40 kg x 1200; the carton has no purchase price.
    assert overview["summary"]["stock_value"] == pytest.approx(3000 * 250 + 40 * 1200)
    assert overview["summary"]["valued_products"] == 2
    assert overview["summary"]["unvalued_products"] == 1
    assert _row(overview, env["carton"])["value"] is None


def test_blocked_dormant_and_threshold_signals(db, env):
    overview = _overview(db)
    film = _row(overview, env["film"])
    assert film["blocked_on_hand"] == 40
    assert film["is_dormant"] is True
    assert film["idle_days"] == 90
    assert film["coverage_status"] == "idle"

    carton = _row(overview, env["carton"])
    assert carton["is_dormant"] is True
    assert overview["summary"]["below_threshold"] == 2  # semoule 3000 < 5000, carton 60 < 100
    assert overview["summary"]["blocked_products"] == 1
    assert overview["summary"]["dormant_count"] == 2


def test_period_flows_are_kept_per_unit_and_corrections_are_listed(db, env):
    overview = _overview(db)
    kg = next(f for f in overview["flow_by_uom"] if f["uom_id"] == env["kg"])
    assert kg["inbound"] == 9000
    assert kg["consumed"] == pytest.approx(300 * 29)  # 29 consumption days fall inside the 30-day period
    assert kg["corrections"] == -50
    assert all(f["uom_id"] != env["piece"] for f in overview["flow_by_uom"])  # the carton receipt is outside the period

    assert overview["summary"]["corrections_count"] == 1
    assert [c["reason"] for c in overview["corrections"]] == ["count"]
    assert _row(overview, env["semoule"])["period_corrections"] == -50

    by_type = {m["move_type"]: m["count"] for m in overview["moves_by_type"]}
    assert by_type == {"production_consumption": 29, "receipt": 1, "adjustment": 1}


def test_daily_series_is_per_day_and_per_unit(db, env):
    overview = _overview(db, date_from=TODAY - datetime.timedelta(days=3), date_to=TODAY - datetime.timedelta(days=1))
    days = [(d["day"], d["uom_id"], d["inbound"], d["outbound"]) for d in overview["daily"]]
    assert days == [
        ((TODAY - datetime.timedelta(days=3)).isoformat(), env["kg"], 0.0, 300.0),
        ((TODAY - datetime.timedelta(days=2)).isoformat(), env["kg"], 0.0, 300.0),
        ((TODAY - datetime.timedelta(days=1)).isoformat(), env["kg"], 0.0, 300.0),
    ]


def test_expiring_lots_within_the_horizon_only(db, env):
    overview = _overview(db)
    numbers = [(lot["lot_number"], lot["days_until_expiry"], lot["quantity_on_hand"]) for lot in overview["expiring_lots"]]
    assert numbers == [("L-PAST", -2, 0.0), ("L-SOON", 10, 15.0)]
    assert overview["summary"]["lots_expired"] == 1
    assert overview["summary"]["lots_expiring_soon"] == 1


def test_another_tenant_sees_nothing(db, env):
    overview = _overview(db, tenant_id="integration-test-warehouse-analytics-other")
    assert overview["products"] == []
    assert overview["summary"]["stock_value"] == 0
