"""Integration tests for product barcodes and scan resolution."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.warehouse.api.barcode_service import BarcodeService
from modules.warehouse.api.lot_service import LotService

TENANT = "integration-test-barcodes"
PACKET = "4006381333931"
CARTON = "14006381333938"


@pytest.fixture
def env(db):
    actor, uom, product, location = (str(ULID()) for _ in range(4))
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'pc', 'Piece', 'unit')", (uom, TENANT))
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, 'BC-SPAG-500', 'Spaghetti 500g', %s)",
        (product, TENANT, uom),
    )
    location_code = f"BIN-{ULID()}"
    db.execute(
        "INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Bin')", (location, TENANT, location_code)
    )
    service = BarcodeService(db)
    packet = service.create_barcode(tenant_id=TENANT, actor_id=actor, product_id=product, barcode=PACKET, barcode_type="gtin")
    carton = service.create_barcode(
        tenant_id=TENANT, actor_id=actor, product_id=product, barcode=CARTON, barcode_type="gtin", units_per_scan=20, label="Carton"
    )
    assert isinstance(packet, Ok) and isinstance(carton, Ok)
    return {"actor": actor, "product": product, "location": location, "location_code": location_code, "carton": carton.value}


def test_a_packet_scan_resolves_to_one_unit(db, env):
    resolved = BarcodeService(db).resolve(tenant_id=TENANT, code=PACKET)
    assert (resolved["kind"], resolved["product_id"], resolved["quantity"], resolved["matched_by"]) == ("product", env["product"], 1.0, "barcode")


def test_a_carton_scan_resolves_to_its_units_per_scan(db, env):
    resolved = BarcodeService(db).resolve(tenant_id=TENANT, code=CARTON)
    assert resolved["quantity"] == 20.0


def test_a_gs1_label_resolves_product_lot_expiry_and_count(db, env):
    lot = LotService(db).register_lot(tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], lot_number="4187SNL")
    assert isinstance(lot, Ok), getattr(lot, "message", "")
    resolved = BarcodeService(db).resolve(tenant_id=TENANT, code=f"(01){CARTON}(17)270331(10)4187SNL(37)3")
    assert resolved["kind"] == "product" and resolved["matched_by"] == "gs1"
    assert resolved["quantity"] == 60.0
    assert resolved["lot_number"] == "4187SNL"
    assert resolved["lot_id"] == lot.value.id
    assert resolved["expiry_date"] == datetime.date(2027, 3, 31).isoformat()


def test_sku_and_location_codes_still_resolve(db, env):
    service = BarcodeService(db)
    assert service.resolve(tenant_id=TENANT, code="bc-spag-500")["product_id"] == env["product"]
    location = service.resolve(tenant_id=TENANT, code=env["location_code"])
    assert (location["kind"], location["location_id"]) == ("location", env["location"])


def test_an_unregistered_code_is_unknown_not_an_error(db, env):
    assert BarcodeService(db).resolve(tenant_id=TENANT, code="NOPE-123")["kind"] == "unknown"


def test_the_same_code_cannot_be_assigned_twice(db, env):
    result = BarcodeService(db).create_barcode(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], barcode="0" + PACKET, barcode_type="gtin"
    )
    assert isinstance(result, Err) and result.code == "DUPLICATE_BARCODE"


def test_a_mistyped_gtin_is_refused(db, env):
    result = BarcodeService(db).create_barcode(
        tenant_id=TENANT, actor_id=env["actor"], product_id=env["product"], barcode="4006381333932", barcode_type="gtin"
    )
    assert isinstance(result, Err) and result.code == "INVALID_GTIN"


def test_update_changes_only_the_given_fields_and_is_audited(db, env):
    result = BarcodeService(db).update_barcode(tenant_id=TENANT, actor_id=env["actor"], barcode_id=env["carton"].id, units_per_scan=24)
    assert isinstance(result, Ok)
    assert (result.value.units_per_scan, result.value.label, result.value.barcode) == (24.0, "Carton", CARTON)
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = 'product_barcode.updated'",
        (TENANT, env["carton"].id),
    ).fetchone()
    assert audit[0] == {"units_per_scan": 24}
