"""Integration tests for spare-parts requests on a maintenance job, against a real database.

The chef asks for parts, the supervisor decides line by line: what is on hand is issued
from a warehouse location (a `maintenance` stock move), the rest is published for
procurement to draft a purchase order. A refused approval writes nothing at all.
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
from modules.maintenance.api.parts_service import PartsService, list_part_requests
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService

T = "integration-test-parts"
OTHER_TENANT = "integration-test-parts-other"
TODAY = datetime.date.today()
EVENT = "maintenance.parts.purchase_requested"
PARTS_LINK = "/maintenance?tab=parts"


def _user(db, full_name, *, tenant=T, permissions=()):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, 'x', %s)",
        (user_id, tenant, f"{user_id}@test.local", full_name),
    )
    for permission in permissions:
        db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s)", (user_id, permission))
    return user_id


def _uom(db, code, name, category, *, integer_only=False, tenant=T):
    uom_id = str(ULID())
    db.execute(
        "INSERT INTO core.uoms (id, tenant_id, code, name, category, is_integer_only) VALUES (%s, %s, %s, %s, %s, %s)",
        (uom_id, tenant, code, name, category, integer_only),
    )
    return uom_id


def _product(db, sku, name, uom_id, *, tenant=T):
    product_id = str(ULID())
    db.execute(
        "INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)",
        (product_id, tenant, sku, name, uom_id),
    )
    return product_id


def _location(db, actor, code, name, **extra):
    created = LocationService(db).create_location(tenant_id=T, actor_id=actor, code=code, name=name, **extra)
    assert isinstance(created, Ok), created
    return created.value.id


def _stock(db, actor, product_id, location_id, quantity):
    received = StockService(db).receive_stock(
        tenant_id=T, product_id=product_id, location_id=location_id, quantity=quantity,
        correlation_id=str(ULID()), reference="parts-test-setup", actor_id=actor,
    )
    assert isinstance(received, Ok), received


@pytest.fixture
def ctx(db):
    sup = _user(db, "Sara Superviseur", permissions=("maintenance.plan_jobs",))
    chef = _user(db, "Chef Keita", permissions=("maintenance.execute_jobs",))
    other = _user(db, "Autre Chef", permissions=("maintenance.execute_jobs",))
    machine = EquipmentService(db).create_equipment(
        tenant_id=T, actor_id=sup, work_center_id="wc-1", code="PRESSE-1", name="Presse 1"
    ).value.id
    created = JobService(db).create_job(
        tenant_id=T, actor_id=sup, equipment_id=machine, title="Roulement bruyant", description=None,
        kind="corrective", priority="normal", due_date=TODAY, stops_machine=False,
        checkpoint_ids=[], tasks=[{"label": "Changer le roulement", "action": "replace"}], chef_user_id=chef,
    )
    assert isinstance(created, Ok), created
    job_id = created.value
    number = job_detail(db, T, job_id, TODAY)["number"]

    piece = _uom(db, "pc", "Pièce", "unit", integer_only=True)
    litre = _uom(db, "L", "Litre", "volume")
    bearing = _product(db, "PDR-ROUL-6204", "Roulement 6204", piece)
    belt = _product(db, "PDR-COURROIE", "Courroie trapézoïdale", piece)
    oil = _product(db, "PDR-HUILE", "Huile hydraulique", litre)
    store = _location(db, sup, "MAG-PDR", "Magasin pièces")
    annex = _location(db, sup, "MAG-ANNEXE", "Annexe atelier")
    return SimpleNamespace(
        sup=sup, chef=chef, other=other, machine=machine, job=job_id, number=number,
        piece=piece, litre=litre, bearing=bearing, belt=belt, oil=oil, store=store, annex=annex,
    )


def _request(db, ctx, lines, *, actor=None, note=None, actor_can_plan=False, job_id=None):
    return PartsService(db).create_request(
        tenant_id=T,
        actor_id=actor or ctx.chef,
        job_id=job_id or ctx.job,
        lines=lines,
        note=note,
        actor_can_plan=actor_can_plan,
    )


def _approve(db, ctx, request_id, lines, *, note=None):
    return PartsService(db).approve(
        tenant_id=T, actor_id=ctx.sup, request_id=request_id, lines=lines, note=note, correlation_id=str(ULID())
    )


def _one(db, request_id):
    [request] = [r for r in list_part_requests(db, T) if r["id"] == request_id]
    return request


def _maintenance_moves(db):
    rows = db.execute(
        """
        SELECT product_id, location_id, quantity, reference, actor_id
        FROM warehouse.stock_moves
        WHERE tenant_id = %s AND move_type = 'maintenance'
        ORDER BY created_at, id
        """,
        (T,),
    ).fetchall()
    return [(r[0], r[1], float(r[2]), r[3], r[4]) for r in rows]


def _purchase_events(db):
    return [
        row[0]
        for row in db.execute(
            "SELECT payload FROM events.outbox WHERE tenant_id = %s AND event_type = %s ORDER BY created_at", (T, EVENT)
        ).fetchall()
    ]


def _available(db, product_id, location_id):
    return StockService(db).get_available_quantity(T, product_id, location_id)


def _notifications(db, user_id):
    rows = db.execute(
        """
        SELECT kind, title, title_fr, body, link FROM core.notifications
        WHERE tenant_id = %s AND user_id = %s AND kind LIKE 'maintenance.parts%%'
        ORDER BY created_at, id
        """,
        (T, user_id),
    ).fetchall()
    return [{"kind": r[0], "title": r[1], "title_fr": r[2], "body": r[3], "link": r[4]} for r in rows]


def _bearing_and_belt(ctx, bearing_qty=10, belt_qty=2):
    return [
        {"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": bearing_qty},
        {"product_id": ctx.belt, "uom_id": ctx.piece, "quantity": belt_qty},
    ]


# ---- request -> approve -----------------------------------------------------------


def test_request_then_approve_issues_stock_and_publishes_purchase_for_remainder(db, ctx):
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 4)
    second_sup = _user(db, "Second Superviseur", permissions=("maintenance.plan_jobs",))

    created = _request(db, ctx, _bearing_and_belt(ctx), note="Roulement HS, courroie usée")
    assert isinstance(created, Ok), created
    request_id = created.value

    pending = _one(db, request_id)
    assert pending["status"] == "pending"
    assert pending["job_id"] == ctx.job and pending["job_number"] == ctx.number
    assert pending["equipment_name"] == "Presse 1"
    assert pending["note"] == "Roulement HS, courroie usée"
    assert (pending["requested_by"], pending["requested_by_name"]) == (ctx.chef, "Chef Keita")
    assert pending["decided_by"] is None and pending["decided_at"] is None
    bearing_line, belt_line = pending["lines"]
    assert (bearing_line["product_id"], bearing_line["product_name"], bearing_line["uom_code"]) == (
        ctx.bearing, "Roulement 6204", "pc",
    )
    assert (bearing_line["quantity"], belt_line["quantity"]) == (10, 2)
    assert bearing_line["issued_quantity"] is None and bearing_line["purchase_quantity"] is None

    # every supervisor is told, with the link to the parts tab; the requester is not
    for supervisor in (ctx.sup, second_sup):
        [asked] = _notifications(db, supervisor)
        assert (asked["kind"], asked["link"]) == ("maintenance.parts_requested", PARTS_LINK)
        assert ctx.number in asked["title"] and "Presse 1" in asked["title"]
        assert ctx.number in asked["title_fr"] and "Presse 1" in asked["title_fr"]
    assert _notifications(db, ctx.chef) == []

    availability = PartsService(db).availability(T, request_id)
    assert availability == {
        "lines": [
            {
                "line_id": bearing_line["id"],
                "product_id": ctx.bearing,
                "locations": [{"location_id": ctx.store, "location_name": "Magasin pièces", "available": 4.0, "in_spare_parts": False}],
            },
            {"line_id": belt_line["id"], "product_id": ctx.belt, "locations": []},
        ]
    }

    approved = _approve(
        db,
        ctx,
        request_id,
        [
            {"line_id": bearing_line["id"], "location_id": ctx.store, "issue_quantity": 4},
            {"line_id": belt_line["id"], "location_id": None, "issue_quantity": 0},
        ],
        note="Le reste est commandé",
    )
    assert isinstance(approved, Ok), approved

    # what was on hand left the warehouse as a maintenance move against the job
    assert _maintenance_moves(db) == [(ctx.bearing, ctx.store, 4.0, f"maintenance:{ctx.number}", ctx.sup)]
    assert _available(db, ctx.bearing, ctx.store) == 0

    # the remainder is published once, purchase lines only
    [envelope] = _purchase_events(db)
    assert envelope["event_type"] == EVENT and envelope["producer"] == "maintenance" and envelope["tenant_id"] == T
    assert envelope["payload"] == {
        "request_id": request_id,
        "job_number": ctx.number,
        "lines": [
            {"line_id": bearing_line["id"], "product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 6.0},
            {"line_id": belt_line["id"], "product_id": ctx.belt, "uom_id": ctx.piece, "quantity": 2.0},
        ],
    }

    decided = _one(db, request_id)
    assert decided["status"] == "approved"
    assert (decided["decided_by"], decided["decided_by_name"]) == (ctx.sup, "Sara Superviseur")
    assert decided["decided_at"] is not None and decided["decision_note"] == "Le reste est commandé"
    split, purchase = decided["lines"]
    assert (split["location_id"], split["issued_quantity"], split["purchase_quantity"]) == (ctx.store, 4, 6)
    assert (purchase["location_id"], purchase["issued_quantity"], purchase["purchase_quantity"]) == (None, 0, 2)

    # the job page carries the request and its history
    detail = job_detail(db, T, ctx.job, TODAY)
    assert [r["id"] for r in detail["part_requests"]] == [request_id]
    assert detail["part_requests"][0] == decided
    kinds = [e["kind"] for e in detail["timeline"]]
    assert kinds[-2:] == ["parts_requested", "parts_approved"]
    assert detail["timeline"][-1]["payload"]["request_id"] == request_id

    # the requester learns the decision
    [told] = _notifications(db, ctx.chef)
    assert (told["kind"], told["link"]) == ("maintenance.parts_approved", PARTS_LINK)
    assert ctx.number in told["title_fr"]


def test_approve_fully_from_stock_publishes_no_purchase_event(db, ctx):
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 5)
    request_id = _request(db, ctx, [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 2}]).value
    [line] = _one(db, request_id)["lines"]

    assert isinstance(
        _approve(db, ctx, request_id, [{"line_id": line["id"], "location_id": ctx.store, "issue_quantity": 2}]), Ok
    )

    assert _maintenance_moves(db) == [(ctx.bearing, ctx.store, 2.0, f"maintenance:{ctx.number}", ctx.sup)]
    assert _available(db, ctx.bearing, ctx.store) == 3
    assert _purchase_events(db) == []
    [line] = _one(db, request_id)["lines"]
    assert (line["issued_quantity"], line["purchase_quantity"]) == (2, 0)


def test_approve_more_than_available_fails_and_changes_nothing(db, ctx):
    """Review focus: the first line is perfectly issuable, the second is not. The whole
    approval is refused before any stock moves -- nothing here relies on a rollback."""
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 4)
    _stock(db, ctx.sup, ctx.belt, ctx.store, 1)
    request_id = _request(db, ctx, _bearing_and_belt(ctx, bearing_qty=4, belt_qty=3)).value
    bearing_line, belt_line = _one(db, request_id)["lines"]
    events_before = db.execute("SELECT count(*) FROM maintenance.job_events WHERE job_id = %s", (ctx.job,)).fetchone()[0]

    refused = _approve(
        db,
        ctx,
        request_id,
        [
            {"line_id": bearing_line["id"], "location_id": ctx.store, "issue_quantity": 4},
            {"line_id": belt_line["id"], "location_id": ctx.store, "issue_quantity": 3},
        ],
    )

    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_STOCK"
    assert refused.message_fr
    assert _maintenance_moves(db) == []
    assert _purchase_events(db) == []
    assert _available(db, ctx.bearing, ctx.store) == 4
    assert _available(db, ctx.belt, ctx.store) == 1
    still = _one(db, request_id)
    assert still["status"] == "pending" and still["decided_by"] is None
    assert all(
        (line["location_id"], line["issued_quantity"], line["purchase_quantity"]) == (None, None, None)
        for line in still["lines"]
    )
    events_after = db.execute("SELECT count(*) FROM maintenance.job_events WHERE job_id = %s", (ctx.job,)).fetchone()[0]
    assert events_after == events_before
    assert _notifications(db, ctx.chef) == []


def test_two_lines_of_one_product_cannot_take_more_than_the_location_holds(db, ctx):
    """Each line alone fits the 5 on hand; together they ask for 6. Refused up front, nothing issued."""
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 5)
    lines = [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 3}] * 2
    request_id = _request(db, ctx, lines).value
    first, second = _one(db, request_id)["lines"]

    refused = _approve(
        db,
        ctx,
        request_id,
        [
            {"line_id": first["id"], "location_id": ctx.store, "issue_quantity": 3},
            {"line_id": second["id"], "location_id": ctx.store, "issue_quantity": 3},
        ],
    )
    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_STOCK"
    assert _maintenance_moves(db) == []

    # 3 + 2 fits: the sixth piece goes to purchase
    assert isinstance(
        _approve(
            db,
            ctx,
            request_id,
            [
                {"line_id": first["id"], "location_id": ctx.store, "issue_quantity": 3},
                {"line_id": second["id"], "location_id": ctx.store, "issue_quantity": 2},
            ],
        ),
        Ok,
    )
    assert [move[2] for move in _maintenance_moves(db)] == [3.0, 2.0]
    assert _available(db, ctx.bearing, ctx.store) == 0
    [envelope] = _purchase_events(db)
    assert envelope["payload"]["lines"] == [
        {"line_id": second["id"], "product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 1.0}
    ]


def test_reserved_and_quarantined_stock_is_not_available_to_issue(db, ctx):
    quarantine = _location(db, ctx.sup, "QUAR", "Quarantaine", is_blocked=True, blocked_reason="non conforme")
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 5)
    _stock(db, ctx.sup, ctx.bearing, quarantine, 9)
    reserved = StockService(db).reserve_stock(
        tenant_id=T, product_id=ctx.bearing, location_id=ctx.store, quantity=3,
        correlation_id=str(ULID()), reference="another-need", actor_id=ctx.sup,
    )
    assert isinstance(reserved, Ok), reserved
    request_id = _request(db, ctx, [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 4}]).value
    [line] = _one(db, request_id)["lines"]

    # 5 on hand - 3 reserved; the quarantine location is not offered at all
    assert PartsService(db).availability(T, request_id)["lines"][0]["locations"] == [
        {"location_id": ctx.store, "location_name": "Magasin pièces", "available": 2.0, "in_spare_parts": False}
    ]
    for location, quantity in ((ctx.store, 3), (quarantine, 1)):
        refused = _approve(db, ctx, request_id, [{"line_id": line["id"], "location_id": location, "issue_quantity": quantity}])
        assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_STOCK"
    assert _maintenance_moves(db) == []


def test_a_reservation_made_after_the_check_is_still_honoured(db, ctx, monkeypatch):
    """The race: approval checks what is free, then issues. If a reservation lands in
    between, the issue itself (under the stock row lock) must refuse to take reserved
    stock. Simulated by letting the check see the shelf as it was before the reservation."""
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 5)
    request_id = _request(db, ctx, [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 4}]).value
    [line] = _one(db, request_id)["lines"]
    stale_free = StockService(db).get_available_quantity(T, ctx.bearing, ctx.store)
    reserved = StockService(db).reserve_stock(
        tenant_id=T, product_id=ctx.bearing, location_id=ctx.store, quantity=3,
        correlation_id=str(ULID()), reference="sales-order", actor_id=ctx.sup,
    )
    assert isinstance(reserved, Ok), reserved
    monkeypatch.setattr(StockService, "get_available_quantity", lambda self, *args: stale_free)

    refused = _approve(db, ctx, request_id, [{"line_id": line["id"], "location_id": ctx.store, "issue_quantity": 4}])

    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_STOCK"
    assert refused.message_fr
    assert _maintenance_moves(db) == []
    on_hand, held = db.execute(
        "SELECT quantity_on_hand, quantity_reserved FROM warehouse.stock_items WHERE product_id = %s AND location_id = %s",
        (ctx.bearing, ctx.store),
    ).fetchone()
    assert (float(on_hand), float(held)) == (5.0, 3.0)


def test_availability_lists_every_location_holding_the_part(db, ctx):
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 4)
    _stock(db, ctx.sup, ctx.bearing, ctx.annex, 1)
    _stock(db, ctx.sup, ctx.oil, ctx.annex, 12.5)
    request_id = _request(
        db,
        ctx,
        [
            {"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 2},
            {"product_id": ctx.oil, "uom_id": ctx.litre, "quantity": 1.5},
        ],
    ).value

    lines = PartsService(db).availability(T, request_id)["lines"]

    assert [line["product_id"] for line in lines] == [ctx.bearing, ctx.oil]
    assert lines[0]["locations"] == [
        {"location_id": ctx.annex, "location_name": "Annexe atelier", "available": 1.0, "in_spare_parts": False},
        {"location_id": ctx.store, "location_name": "Magasin pièces", "available": 4.0, "in_spare_parts": False},
    ]
    assert lines[1]["locations"] == [{"location_id": ctx.annex, "location_name": "Annexe atelier", "available": 12.5, "in_spare_parts": False}]
    assert PartsService(db).availability(T, "no-such-request") is None
    assert PartsService(db).availability(OTHER_TENANT, request_id) is None


def test_a_fractional_split_keeps_exact_quantities(db, ctx):
    _stock(db, ctx.sup, ctx.oil, ctx.store, 0.1)
    request_id = _request(db, ctx, [{"product_id": ctx.oil, "uom_id": ctx.litre, "quantity": 0.3}]).value
    [line] = _one(db, request_id)["lines"]

    assert isinstance(
        _approve(db, ctx, request_id, [{"line_id": line["id"], "location_id": ctx.store, "issue_quantity": 0.1}]), Ok
    )

    [line] = _one(db, request_id)["lines"]
    assert (line["issued_quantity"], line["purchase_quantity"]) == (0.1, 0.2)
    assert _purchase_events(db)[0]["payload"]["lines"][0]["quantity"] == 0.2


def test_approve_needs_every_line_once_a_location_to_issue_and_a_sane_quantity(db, ctx):
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 20)
    request_id = _request(db, ctx, _bearing_and_belt(ctx, bearing_qty=4, belt_qty=3)).value
    bearing_line, belt_line = _one(db, request_id)["lines"]
    belt_to_purchase = {"line_id": belt_line["id"], "location_id": None, "issue_quantity": 0}

    def refusal(lines):
        result = _approve(db, ctx, request_id, lines)
        assert isinstance(result, Err), result
        assert result.message_fr
        return result.code

    bearing = {"line_id": bearing_line["id"], "location_id": ctx.store, "issue_quantity": 4}
    assert refusal([bearing]) == "LINES_INCOMPLETE"
    assert refusal([bearing, bearing, belt_to_purchase]) == "LINES_INCOMPLETE"
    assert refusal([bearing, belt_to_purchase, {"line_id": "nope", "location_id": None, "issue_quantity": 0}]) == "UNKNOWN_LINE"
    assert refusal([{**bearing, "location_id": None}, belt_to_purchase]) == "LOCATION_REQUIRED"
    assert refusal([{**bearing, "location_id": "  "}, belt_to_purchase]) == "LOCATION_REQUIRED"
    assert refusal([{**bearing, "issue_quantity": 5}, belt_to_purchase]) == "INVALID_QUANTITY"
    assert refusal([{**bearing, "issue_quantity": -1}, belt_to_purchase]) == "INVALID_QUANTITY"
    # a piece is a whole-count unit: half a bearing cannot be issued
    assert refusal([{**bearing, "issue_quantity": 1.5}, belt_to_purchase]) == "QUANTITY_MUST_BE_INTEGER"
    assert refusal([{**bearing, "location_id": "no-such-location"}, belt_to_purchase]) == "INSUFFICIENT_STOCK"

    assert _maintenance_moves(db) == [] and _purchase_events(db) == []
    assert _one(db, request_id)["status"] == "pending"

    unknown = PartsService(db).approve(
        tenant_id=T, actor_id=ctx.sup, request_id="no-such-request", lines=[], note=None, correlation_id=str(ULID())
    )
    assert isinstance(unknown, Err) and unknown.code == "NOT_FOUND"
    elsewhere = PartsService(db).approve(
        tenant_id=OTHER_TENANT, actor_id=ctx.sup, request_id=request_id, lines=[bearing, belt_to_purchase], note=None,
        correlation_id=str(ULID()),
    )
    assert isinstance(elsewhere, Err) and elsewhere.code == "NOT_FOUND"


def test_a_decided_request_cannot_be_decided_again(db, ctx):
    request_id = _request(db, ctx, [{"product_id": ctx.belt, "uom_id": ctx.piece, "quantity": 1}]).value
    [line] = _one(db, request_id)["lines"]
    to_purchase = [{"line_id": line["id"], "location_id": None, "issue_quantity": 0}]
    assert isinstance(_approve(db, ctx, request_id, to_purchase), Ok)

    again = _approve(db, ctx, request_id, to_purchase)
    assert isinstance(again, Err) and again.code == "ALREADY_DECIDED"
    rejected = PartsService(db).reject(tenant_id=T, actor_id=ctx.sup, request_id=request_id, note="trop tard")
    assert isinstance(rejected, Err) and rejected.code == "ALREADY_DECIDED"
    assert len(_purchase_events(db)) == 1
    assert _one(db, request_id)["status"] == "approved"


# ---- reject -------------------------------------------------------------------------


def test_reject_requires_note(db, ctx):
    _stock(db, ctx.sup, ctx.bearing, ctx.store, 4)
    request_id = _request(db, ctx, [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 2}]).value
    parts = PartsService(db)

    for blank in (None, "", "   "):
        refused = parts.reject(tenant_id=T, actor_id=ctx.sup, request_id=request_id, note=blank)
        assert isinstance(refused, Err) and refused.code == "NOTE_REQUIRED"
        assert refused.message_fr
    assert _one(db, request_id)["status"] == "pending"
    assert _notifications(db, ctx.chef) == []

    assert isinstance(parts.reject(tenant_id=T, actor_id=ctx.sup, request_id=request_id, note="  Pièce déjà en atelier "), Ok)

    rejected = _one(db, request_id)
    assert rejected["status"] == "rejected"
    assert (rejected["decided_by"], rejected["decision_note"]) == (ctx.sup, "Pièce déjà en atelier")
    assert rejected["decided_at"] is not None
    assert rejected["lines"][0]["issued_quantity"] is None and rejected["lines"][0]["purchase_quantity"] is None
    assert _maintenance_moves(db) == [] and _purchase_events(db) == []
    assert _available(db, ctx.bearing, ctx.store) == 4
    [told] = _notifications(db, ctx.chef)
    assert (told["kind"], told["body"], told["link"]) == ("maintenance.parts_rejected", "Pièce déjà en atelier", PARTS_LINK)
    timeline = job_detail(db, T, ctx.job, TODAY)["timeline"]
    assert timeline[-1]["kind"] == "parts_rejected"
    assert timeline[-1]["payload"] == {"request_id": request_id, "note": "Pièce déjà en atelier"}

    unknown = parts.reject(tenant_id=T, actor_id=ctx.sup, request_id="no-such-request", note="x")
    assert isinstance(unknown, Err) and unknown.code == "NOT_FOUND"


# ---- create -------------------------------------------------------------------------


def test_cannot_request_on_closed_job(db, ctx):
    line = [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 1}]

    db.execute("UPDATE maintenance.jobs SET status = 'closed', closed_at = NOW() WHERE id = %s", (ctx.job,))
    closed = _request(db, ctx, line)
    assert isinstance(closed, Err) and closed.code == "INVALID_TRANSITION"
    assert closed.message_fr

    db.execute("UPDATE maintenance.jobs SET status = 'cancelled' WHERE id = %s", (ctx.job,))
    cancelled = _request(db, ctx, line)
    assert isinstance(cancelled, Err) and cancelled.code == "INVALID_TRANSITION"

    assert list_part_requests(db, T) == []
    assert _notifications(db, ctx.sup) == []

    for open_status in ("planned", "assigned", "in_progress", "submitted", "rework"):
        db.execute("UPDATE maintenance.jobs SET status = %s WHERE id = %s", (open_status, ctx.job))
        assert isinstance(_request(db, ctx, line), Ok), open_status


def test_only_the_job_chef_or_a_supervisor_requests_parts(db, ctx):
    line = [{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 1}]

    stranger = _request(db, ctx, line, actor=ctx.other)
    assert isinstance(stranger, Err) and stranger.code == "NOT_JOB_CHEF"
    assert list_part_requests(db, T) == []

    by_supervisor = _request(db, ctx, line, actor=ctx.sup, actor_can_plan=True)
    assert isinstance(by_supervisor, Ok)
    assert _one(db, by_supervisor.value)["requested_by"] == ctx.sup

    missing = _request(db, ctx, line, job_id="no-such-job")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"


def test_request_lines_are_checked_before_anything_is_written(db, ctx):
    foreign_uom = _uom(db, "pc", "Pièce", "unit", tenant=OTHER_TENANT)
    foreign_product = _product(db, "PDR-X", "Ailleurs", foreign_uom, tenant=OTHER_TENANT)

    def refusal(lines):
        result = _request(db, ctx, lines)
        assert isinstance(result, Err), result
        assert result.message_fr
        return result.code

    assert refusal([]) == "INVALID_LINES"
    assert refusal([{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 0}]) == "INVALID_QUANTITY"
    assert refusal([{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": -2}]) == "INVALID_QUANTITY"
    assert refusal([{"product_id": "no-such-product", "uom_id": ctx.piece, "quantity": 1}]) == "UNKNOWN_PRODUCT"
    assert refusal([{"product_id": foreign_product, "uom_id": foreign_uom, "quantity": 1}]) == "UNKNOWN_PRODUCT"
    # stock is counted and issued in the product's own unit
    assert refusal([{"product_id": ctx.bearing, "uom_id": ctx.litre, "quantity": 1}]) == "UOM_MISMATCH"
    assert refusal([{"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 1.5}]) == "QUANTITY_MUST_BE_INTEGER"
    # one bad line refuses the whole request
    assert (
        refusal(
            [
                {"product_id": ctx.belt, "uom_id": ctx.piece, "quantity": 1},
                {"product_id": ctx.bearing, "uom_id": ctx.piece, "quantity": 0},
            ]
        )
        == "INVALID_QUANTITY"
    )

    assert list_part_requests(db, T) == []
    assert _notifications(db, ctx.sup) == []


# ---- reads --------------------------------------------------------------------------


def test_list_part_requests_filters_and_has_the_contract_shape(db, ctx):
    line = [{"product_id": ctx.belt, "uom_id": ctx.piece, "quantity": 1}]
    first = _request(db, ctx, line, note="  ").value
    second = _request(db, ctx, line).value
    third = _request(db, ctx, line).value
    other_job = JobService(db).create_job(
        tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Autre", description=None, kind="corrective",
        priority="normal", due_date=TODAY, stops_machine=False, checkpoint_ids=[],
        tasks=[{"label": "Voir", "action": "inspect"}], chef_user_id=ctx.chef,
    ).value
    elsewhere = _request(db, ctx, line, job_id=other_job).value

    PartsService(db).reject(tenant_id=T, actor_id=ctx.sup, request_id=second, note="non")
    [third_line] = _one(db, third)["lines"]
    _approve(db, ctx, third, [{"line_id": third_line["id"], "location_id": None, "issue_quantity": 0}])

    # newest first
    assert [r["id"] for r in list_part_requests(db, T)] == [elsewhere, third, second, first]
    assert [r["id"] for r in list_part_requests(db, T, status="pending")] == [elsewhere, first]
    assert [r["id"] for r in list_part_requests(db, T, status="approved")] == [third]
    assert [r["id"] for r in list_part_requests(db, T, status="rejected")] == [second]
    assert [r["id"] for r in list_part_requests(db, T, job_id=ctx.job)] == [third, second, first]
    assert [r["id"] for r in list_part_requests(db, T, status="pending", job_id=ctx.job)] == [first]
    assert list_part_requests(db, OTHER_TENANT) == []

    request = _one(db, first)
    assert set(request) == {
        "id", "job_id", "job_number", "equipment_name", "status", "note", "requested_by", "requested_by_name",
        "requested_at", "decided_by", "decided_by_name", "decided_at", "decision_note", "lines",
    }
    assert set(request["lines"][0]) == {
        "id", "product_id", "product_name", "uom_id", "uom_code", "quantity", "location_id", "issued_quantity",
        "purchase_quantity",
    }
    # a blank note is no note; timestamps are ISO-8601 with an offset
    assert request["note"] is None and request["decided_by_name"] is None and request["decision_note"] is None
    assert datetime.datetime.fromisoformat(request["requested_at"]).tzinfo is not None
    assert isinstance(request["lines"][0]["quantity"], float)
    assert datetime.datetime.fromisoformat(_one(db, second)["decided_at"]).tzinfo is not None


def test_lines_keep_the_order_they_were_requested_in(db, ctx):
    products = [ctx.belt, ctx.bearing, ctx.belt, ctx.bearing, ctx.belt, ctx.bearing]
    request_id = _request(
        db, ctx, [{"product_id": p, "uom_id": ctx.piece, "quantity": index + 1} for index, p in enumerate(products)]
    ).value

    lines = _one(db, request_id)["lines"]

    assert [line["product_id"] for line in lines] == products
    assert [line["quantity"] for line in lines] == [1, 2, 3, 4, 5, 6]


def test_every_decision_is_audited(db, ctx):
    request_id = _request(db, ctx, [{"product_id": ctx.belt, "uom_id": ctx.piece, "quantity": 1}]).value
    [line] = _one(db, request_id)["lines"]
    _approve(db, ctx, request_id, [{"line_id": line["id"], "location_id": None, "issue_quantity": 0}])
    other = _request(db, ctx, [{"product_id": ctx.belt, "uom_id": ctx.piece, "quantity": 1}]).value
    PartsService(db).reject(tenant_id=T, actor_id=ctx.sup, request_id=other, note="non")

    rows = db.execute(
        """
        SELECT entity_id, action, actor_id FROM core.audit_log
        WHERE tenant_id = %s AND entity_type = 'maintenance_part_request'
        ORDER BY occurred_at, id
        """,
        (T,),
    ).fetchall()
    assert sorted(rows) == sorted(
        [
            (request_id, "part_request.created", ctx.chef),
            (request_id, "part_request.approved", ctx.sup),
            (other, "part_request.created", ctx.chef),
            (other, "part_request.rejected", ctx.sup),
        ]
    )
