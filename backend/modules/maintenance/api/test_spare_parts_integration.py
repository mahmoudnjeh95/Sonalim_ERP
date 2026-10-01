"""Integration tests for spare parts on checkpoints, against a real database.

A supervisor names the warehouse location spare parts live in (shelves under it
count too). A checkpoint lists the parts its work needs; the map editor offers
the products kept in that location, and a job's check shows each part with what
that location -- and only that location -- has available, shelf by shelf.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.maintenance.api.equipment_service import EquipmentService
from modules.maintenance.api.job_queries import job_detail
from modules.maintenance.api.job_service import JobService
from modules.maintenance.api.map_service import MapService
from modules.maintenance.api.parts_service import PartsService
from modules.maintenance.api.spare_parts_service import SparePartsService
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService

T = "integration-test-spare-parts"
TODAY = datetime.date.today()
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 50


def _user(db, full_name):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, T, f"{user_id}@test.local", full_name),
    )
    return user_id


def _uom(db, code, name, category, *, integer_only=False):
    uom_id = str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, %s, %s, %s, %s)",
        (uom_id, T, code, name, category, integer_only),
    )
    return uom_id


def _product(db, sku, name, uom_id, *, default_location_id=None):
    product_id = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id, default_location_id) VALUES (%s, %s, %s, %s, %s, %s)",
        (product_id, T, sku, name, uom_id, default_location_id),
    )
    return product_id


def _location(db, actor, code, name, **extra):
    created = LocationService(db).create_location(tenant_id=T, actor_id=actor, code=code, name=name, **extra)
    assert isinstance(created, Ok), created
    return created.value.id


def _stock(db, actor, product_id, location_id, quantity):
    received = StockService(db).receive_stock(
        tenant_id=T, product_id=product_id, location_id=location_id, quantity=quantity,
        correlation_id=str(ULID()), reference="spare-parts-test-setup", actor_id=actor,
    )
    assert isinstance(received, Ok), received


@pytest.fixture
def ctx(db):
    sup = _user(db, "Sara Superviseur")
    piece = _uom(db, "pc", "Pièce", "unit", integer_only=True)
    litre = _uom(db, "L", "Litre", "volume")
    store = _location(db, sup, "PDR", "Pièces de rechange", location_type="zone")
    shelf = _location(db, sup, "PDR-B", "Étagère B", parent_location_id=store)
    elsewhere = _location(db, sup, "MP", "Matières premières")
    bearing = _product(db, "PDR-ROUL-6204", "Roulement 6204", piece, default_location_id=store)
    grease = _product(db, "PDR-GRAISSE", "Graisse alimentaire", litre)
    flour = _product(db, "MP-SEMOULE", "Semoule", piece, default_location_id=elsewhere)

    machine = EquipmentService(db).create_equipment(
        tenant_id=T, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    view = MapService(db).create_view(
        tenant_id=T, actor_id=sup, equipment_id=machine, label="Vue avant", image=JPEG_BYTES, mime="image/jpeg"
    ).value["id"]
    return SimpleNamespace(
        sup=sup, piece=piece, litre=litre, store=store, shelf=shelf, elsewhere=elsewhere,
        bearing=bearing, grease=grease, flour=flour, machine=machine, view=view,
    )


def _choose_store(db, ctx):
    chosen = SparePartsService(db).set_location(tenant_id=T, actor_id=ctx.sup, location_id=ctx.store)
    assert isinstance(chosen, Ok), chosen
    return chosen.value


def _add_point(db, ctx, parts, label="Roulement moteur"):
    return MapService(db).add_checkpoint(
        tenant_id=T, actor_id=ctx.sup, view_id=ctx.view, x_pct=10, y_pct=20,
        label=label, action="replace", parts=parts,
    )


# ---- the spare-parts location ---------------------------------------------------------


def test_no_spare_parts_location_until_one_is_chosen(db, ctx):
    assert SparePartsService(db).settings(T) == {"spare_parts_location_id": None, "spare_parts_location_name": None}


def test_choosing_the_location_round_trips_its_name(db, ctx):
    chosen = _choose_store(db, ctx)

    assert chosen == {"spare_parts_location_id": ctx.store, "spare_parts_location_name": "Pièces de rechange"}
    assert SparePartsService(db).settings(T) == chosen


def test_an_unknown_location_is_refused(db, ctx):
    refused = SparePartsService(db).set_location(tenant_id=T, actor_id=ctx.sup, location_id=str(ULID()))

    assert isinstance(refused, Err)
    assert refused.code == "UNKNOWN_LOCATION"


def test_a_blocked_location_is_refused(db, ctx):
    quarantine = _location(db, ctx.sup, "QUAR", "Quarantaine", is_blocked=True, blocked_reason="non conforme")

    refused = SparePartsService(db).set_location(tenant_id=T, actor_id=ctx.sup, location_id=quarantine)

    assert isinstance(refused, Err)
    assert refused.code == "UNKNOWN_LOCATION"


def test_the_location_can_be_cleared(db, ctx):
    _choose_store(db, ctx)

    cleared = SparePartsService(db).set_location(tenant_id=T, actor_id=ctx.sup, location_id=None)

    assert cleared == Ok({"spare_parts_location_id": None, "spare_parts_location_name": None})


def test_location_options_leave_blocked_locations_out(db, ctx):
    _location(db, ctx.sup, "QUAR", "Quarantaine", is_blocked=True, blocked_reason="non conforme")

    names = [option["name"] for option in SparePartsService(db).location_options(T)]

    assert "Pièces de rechange" in names
    assert "Étagère B" in names
    assert "Quarantaine" not in names


# ---- the catalog the map editor picks from ------------------------------------------------


def test_catalog_is_empty_until_a_location_is_chosen(db, ctx):
    assert SparePartsService(db).catalog(T) == {"location_id": None, "location_name": None, "products": []}


def test_catalog_offers_products_kept_in_the_location_or_its_shelves(db, ctx):
    _choose_store(db, ctx)
    _stock(db, ctx.sup, ctx.bearing, ctx.shelf, 4)
    _stock(db, ctx.sup, ctx.grease, ctx.shelf, 2.5)
    _stock(db, ctx.sup, ctx.flour, ctx.elsewhere, 100)

    catalog = SparePartsService(db).catalog(T)

    assert catalog["location_name"] == "Pièces de rechange"
    by_name = {product["name"]: product for product in catalog["products"]}
    # The bearing by its default location, the grease by its stock on a shelf; the flour lives elsewhere.
    assert set(by_name) == {"Roulement 6204", "Graisse alimentaire"}
    bearing = by_name["Roulement 6204"]
    assert bearing["product_id"] == ctx.bearing
    assert bearing["uom_id"] == ctx.piece
    assert bearing["uom_code"] == "pc"
    assert bearing["available"] == 4
    assert bearing["locations"] == [{"location_id": ctx.shelf, "location_name": "Pièces de rechange › Étagère B", "available": 4}]


def test_catalog_offers_a_default_located_product_with_no_stock(db, ctx):
    _choose_store(db, ctx)

    catalog = SparePartsService(db).catalog(T)

    assert [(product["name"], product["available"], product["locations"]) for product in catalog["products"]] == [
        ("Roulement 6204", 0, [])
    ]


# ---- parts on a checkpoint -------------------------------------------------------------


def test_checkpoint_keeps_the_parts_it_needs(db, ctx):
    added = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}, {"product_id": ctx.grease, "quantity": 0.25}])

    assert isinstance(added, Ok), added
    assert added.value["parts"] == [
        {"product_id": ctx.bearing, "product_name": "Roulement 6204", "sku": "PDR-ROUL-6204",
         "uom_id": ctx.piece, "uom_code": "pc", "quantity": 2},
        {"product_id": ctx.grease, "product_name": "Graisse alimentaire", "sku": "PDR-GRAISSE",
         "uom_id": ctx.litre, "uom_code": "L", "quantity": 0.25},
    ]
    view = MapService(db).list_views(tenant_id=T, equipment_id=ctx.machine)[0]
    assert [part["product_name"] for part in view["checkpoints"][0]["parts"]] == ["Roulement 6204", "Graisse alimentaire"]


def test_checkpoint_without_parts_has_an_empty_list(db, ctx):
    added = MapService(db).add_checkpoint(
        tenant_id=T, actor_id=ctx.sup, view_id=ctx.view, x_pct=10, y_pct=20, label="État général", action="inspect"
    )

    assert added.value["parts"] == []


def test_updating_parts_replaces_the_list(db, ctx):
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value

    updated = MapService(db).update_checkpoint(
        tenant_id=T, actor_id=ctx.sup, checkpoint_id=point["id"], parts=[{"product_id": ctx.grease, "quantity": 1}]
    )

    assert [(part["product_name"], part["quantity"]) for part in updated.value["parts"]] == [("Graisse alimentaire", 1)]


def test_updating_without_parts_keeps_them(db, ctx):
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value

    updated = MapService(db).update_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=point["id"], label="Roulement côté réducteur")

    assert [part["product_name"] for part in updated.value["parts"]] == ["Roulement 6204"]


def test_an_empty_parts_list_clears_them(db, ctx):
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value

    updated = MapService(db).update_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=point["id"], parts=[])

    assert updated.value["parts"] == []


@pytest.mark.parametrize(
    ("parts", "code"),
    [
        ([{"product_id": "no-such-product", "quantity": 1}], "UNKNOWN_PRODUCT"),
        ([{"product_id": "BEARING", "quantity": 0}], "INVALID_QUANTITY"),
        ([{"product_id": "BEARING", "quantity": -1}], "INVALID_QUANTITY"),
        # A bearing is counted in whole pieces.
        ([{"product_id": "BEARING", "quantity": 1.5}], "QUANTITY_MUST_BE_INTEGER"),
        ([{"product_id": "BEARING", "quantity": 1}, {"product_id": "BEARING", "quantity": 2}], "DUPLICATE_PART"),
    ],
)
def test_invalid_parts_are_refused_and_nothing_is_written(db, ctx, parts, code):
    parts = [{**part, "product_id": ctx.bearing if part["product_id"] == "BEARING" else part["product_id"]} for part in parts]

    refused = _add_point(db, ctx, parts)

    assert isinstance(refused, Err)
    assert refused.code == code
    assert MapService(db).list_views(tenant_id=T, equipment_id=ctx.machine)[0]["checkpoints"] == []


def test_invalid_parts_on_update_leave_the_point_unchanged(db, ctx):
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value

    refused = MapService(db).update_checkpoint(
        tenant_id=T, actor_id=ctx.sup, checkpoint_id=point["id"], label="Renommé", parts=[{"product_id": ctx.bearing, "quantity": 0}]
    )

    assert isinstance(refused, Err)
    view = MapService(db).list_views(tenant_id=T, equipment_id=ctx.machine)[0]
    assert view["checkpoints"][0]["label"] == "Roulement moteur"
    assert [part["quantity"] for part in view["checkpoints"][0]["parts"]] == [2]


# ---- a job's check ---------------------------------------------------------------------


def _job_from_point(db, ctx, checkpoint_id):
    created = JobService(db).create_job(
        tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Changer le roulement", description=None,
        kind="corrective", priority="normal", due_date=TODAY, stops_machine=False,
        checkpoint_ids=[checkpoint_id], tasks=[], chef_user_id=None,
    )
    assert isinstance(created, Ok), created
    return created.value


def test_job_check_shows_its_parts_with_the_spare_parts_stock_only(db, ctx):
    _choose_store(db, ctx)
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 1)
    _stock(db, ctx.sup, ctx.bearing, ctx.shelf, 4)
    _stock(db, ctx.sup, ctx.bearing, ctx.elsewhere, 9)
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value
    job_id = _job_from_point(db, ctx, point["id"])

    check = job_detail(db, T, job_id, TODAY)["checks"][0]

    assert check["parts"] == [
        {
            "product_id": ctx.bearing, "product_name": "Roulement 6204", "sku": "PDR-ROUL-6204",
            "uom_id": ctx.piece, "uom_code": "pc", "quantity": 2, "available": 5,
            "locations": [
                {"location_id": ctx.store, "location_name": "Pièces de rechange", "available": 1},
                {"location_id": ctx.shelf, "location_name": "Pièces de rechange › Étagère B", "available": 4},
            ],
        }
    ]


def test_job_check_reads_the_points_current_parts(db, ctx):
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value
    job_id = _job_from_point(db, ctx, point["id"])
    MapService(db).update_checkpoint(tenant_id=T, actor_id=ctx.sup, checkpoint_id=point["id"], parts=[{"product_id": ctx.grease, "quantity": 1}])

    check = job_detail(db, T, job_id, TODAY)["checks"][0]

    assert [part["product_name"] for part in check["parts"]] == ["Graisse alimentaire"]


def test_job_check_without_a_location_shows_parts_with_no_stock(db, ctx):
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 3)
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value
    job_id = _job_from_point(db, ctx, point["id"])

    part = job_detail(db, T, job_id, TODAY)["checks"][0]["parts"][0]

    assert (part["available"], part["locations"]) == (0, [])


def test_a_free_task_check_has_no_parts(db, ctx):
    created = JobService(db).create_job(
        tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Nettoyage", description=None,
        kind="corrective", priority="normal", due_date=TODAY, stops_machine=False,
        checkpoint_ids=[], tasks=[{"label": "Nettoyer la trémie", "action": "clean"}], chef_user_id=None,
    )

    assert job_detail(db, T, created.value, TODAY)["checks"][0]["parts"] == []


# ---- approving a parts request ---------------------------------------------------------


def test_availability_marks_the_spare_parts_locations(db, ctx):
    _choose_store(db, ctx)
    _stock(db, ctx.sup, ctx.bearing, ctx.shelf, 4)
    _stock(db, ctx.sup, ctx.bearing, ctx.elsewhere, 9)
    point = _add_point(db, ctx, [{"product_id": ctx.bearing, "quantity": 2}]).value
    job_id = _job_from_point(db, ctx, point["id"])
    requested = PartsService(db).create_request(
        tenant_id=T, actor_id=ctx.sup, job_id=job_id,
        lines=[{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 2}], note=None, actor_can_plan=True,
    )
    assert isinstance(requested, Ok), requested

    locations = PartsService(db).availability(T, requested.value)["lines"][0]["locations"]

    assert {(entry["location_name"], entry["in_spare_parts"]) for entry in locations} == {
        ("Étagère B", True),
        ("Matières premières", False),
    }
