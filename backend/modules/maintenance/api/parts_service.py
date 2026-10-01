"""Spare-parts requests on a maintenance job.

The chef (or a supervisor) asks for parts on an open job; a supervisor decides. On
approval each line is split between what is issued now from a warehouse location the
supervisor picks (`StockService.issue_stock`, move type `maintenance`, reference
`maintenance:<job number>`) and what is left to buy, which is published as
`maintenance.parts.purchase_requested` for procurement to draft a purchase order.

An approval is all or nothing: every line is checked -- the right lines, sane
quantities, a location for anything issued, enough available stock counting the
other lines of the same request -- before the first unit leaves the warehouse, so a
refused approval writes nothing at all.

Stock is read and moved only through the warehouse's public services; products and
units come from the shared kernel. Quantities are handled as `Decimal` so a split of
0.3 L into 0.1 + 0.2 stays exact.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.entities import validate_quantity_for_uom
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.maintenance.api import notifications
from modules.maintenance.api.people import user_names
from modules.maintenance.api.spare_parts_service import SparePartsService
from modules.maintenance.domain.parts import split_line
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.service import StockService

__all__ = ["PURCHASE_REQUESTED_EVENT", "REQUEST_STATUSES", "PartsService", "get_part_request", "list_part_requests"]

PURCHASE_REQUESTED_EVENT = "maintenance.parts.purchase_requested"

_ENTITY = "maintenance_part_request"
REQUEST_STATUSES = ("pending", "approved", "rejected")
# A job that is over takes no more parts.
_CLOSED_JOB_STATUSES = ("closed", "cancelled")
_ZERO = Decimal(0)


def _clean(text: str | None) -> str | None:
    """A typed text with its edges trimmed; blank becomes None."""
    stripped = (text or "").strip()
    return stripped or None


def _decimal(value: object) -> Decimal | None:
    """A finite number as an exact Decimal (through its shortest text, so 0.1 stays 0.1); None otherwise."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _request_not_found(request_id: str) -> Err:
    return Err("NOT_FOUND", f"parts request {request_id} not found", f"demande de pièces {request_id} introuvable")


# ---- reads (PartRequest / PartRequestLine of the API contract) -----------------------


def list_part_requests(
    connection: psycopg.Connection,
    tenant_id: str,
    *,
    status: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
) -> list[dict]:
    """The tenant's parts requests as `PartRequest`s, newest first, each with its lines
    in the order they were asked for. Filters combine: `status`, `job_id`, `request_id`."""
    clauses = ["r.tenant_id = %s"]
    params: list[object] = [tenant_id]
    if status is not None:
        clauses.append("r.status = %s")
        params.append(status)
    if job_id is not None:
        clauses.append("r.job_id = %s")
        params.append(job_id)
    if request_id is not None:
        clauses.append("r.id = %s")
        params.append(request_id)
    rows = connection.execute(
        f"""
        SELECT r.id, r.job_id, j.number, e.name, r.status, r.note, r.requested_by, r.requested_at,
               r.decided_by, r.decided_at, r.decision_note
        FROM maintenance.part_requests r
        JOIN maintenance.jobs j ON j.id = r.job_id
        JOIN maintenance.equipment e ON e.id = j.equipment_id
        WHERE {' AND '.join(clauses)}
        ORDER BY r.requested_at DESC, r.id DESC
        """,
        params,
    ).fetchall()
    if not rows:
        return []

    # Product and unit names come from the shared kernel, which every module may read.
    line_rows = connection.execute(
        """
        SELECT l.request_id, l.id, l.product_id, p.name, l.uom_id, u.code, l.quantity, l.location_id,
               l.issued_quantity, l.purchase_quantity
        FROM maintenance.part_request_lines l
        LEFT JOIN core.products p ON p.id = l.product_id AND p.tenant_id = l.tenant_id
        LEFT JOIN core.uoms u ON u.id = l.uom_id AND u.tenant_id = l.tenant_id
        WHERE l.tenant_id = %s AND l.request_id = ANY(%s)
        ORDER BY l.request_id, l.sort_order, l.id
        """,
        (tenant_id, [row[0] for row in rows]),
    ).fetchall()
    lines: dict[str, list[dict]] = {}
    for (
        line_request_id, line_id, product_id, product_name, uom_id, uom_code, quantity, location_id, issued, purchase,
    ) in line_rows:
        lines.setdefault(line_request_id, []).append(
            {
                "id": line_id,
                "product_id": product_id,
                "product_name": product_name if product_name is not None else product_id,
                "uom_id": uom_id,
                "uom_code": uom_code if uom_code is not None else uom_id,
                "quantity": float(quantity),
                "location_id": location_id,
                "issued_quantity": _number(issued),
                "purchase_quantity": _number(purchase),
            }
        )

    names = user_names(connection, tenant_id, [user for row in rows for user in (row[6], row[8])])
    return [
        {
            "id": rid,
            "job_id": rjob_id,
            "job_number": number,
            "equipment_name": equipment_name,
            "status": rstatus,
            "note": note,
            "requested_by": requested_by,
            "requested_by_name": names.get(requested_by, requested_by),
            "requested_at": requested_at.isoformat(),
            "decided_by": decided_by,
            "decided_by_name": names.get(decided_by, decided_by) if decided_by is not None else None,
            "decided_at": decided_at.isoformat() if decided_at is not None else None,
            "decision_note": decision_note,
            "lines": lines.get(rid, []),
        }
        for (
            rid, rjob_id, number, equipment_name, rstatus, note, requested_by, requested_at,
            decided_by, decided_at, decision_note,
        ) in rows
    ]


def get_part_request(connection: psycopg.Connection, tenant_id: str, request_id: str) -> dict | None:
    """One `PartRequest`, or None when the tenant has no such request."""
    found = list_part_requests(connection, tenant_id, request_id=request_id)
    return found[0] if found else None


# ---- writes -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Request:
    id: str
    job_id: str
    job_number: str
    equipment_name: str
    status: str
    requested_by: str


@dataclass(frozen=True)
class _Line:
    id: str
    product_id: str
    uom_id: str
    quantity: Decimal


@dataclass(frozen=True)
class _Decision:
    line: _Line
    location_id: str | None
    issue: Decimal
    purchase: Decimal


class PartsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- request ---------------------------------------------------------------------

    def create_request(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        job_id: str,
        lines: list[dict],
        note: str | None,
        actor_can_plan: bool,
    ) -> Result[str]:
        """The job's chef (or a supervisor) asks for parts: `lines` are
        `{product_id, uom_id, quantity}`, in the product's own unit. Refused on a closed
        or cancelled job. Every supervisor is told. Returns the new request's id."""
        job = self._connection.execute(
            """
            SELECT j.number, j.status, j.chef_user_id, e.name
            FROM maintenance.jobs j
            JOIN maintenance.equipment e ON e.id = j.equipment_id
            WHERE j.id = %s AND j.tenant_id = %s
            """,
            (job_id, tenant_id),
        ).fetchone()
        if job is None:
            return Err("NOT_FOUND", f"job {job_id} not found", f"intervention {job_id} introuvable")
        number, job_status, chef_user_id, equipment_name = job
        if not actor_can_plan and chef_user_id != actor_id:
            return Err(
                "NOT_JOB_CHEF",
                "only the chef this job is assigned to can request parts for it",
                "seul le chef d'atelier à qui l'intervention est assignée peut y demander des pièces",
            )
        if job_status in _CLOSED_JOB_STATUSES:
            return Err(
                "INVALID_TRANSITION",
                f"no parts can be requested on a {job_status} job",
                "impossible de demander des pièces sur une intervention clôturée ou annulée",
            )

        checked = self._checked_request_lines(tenant_id, lines)
        if isinstance(checked, Err):
            return checked
        note = _clean(note)

        request_id = str(ULID())
        # clock_timestamp(): requests made in one transaction keep their order (newest first in lists).
        self._connection.execute(
            """
            INSERT INTO maintenance.part_requests (id, tenant_id, job_id, status, note, requested_by, requested_at)
            VALUES (%s, %s, %s, 'pending', %s, %s, clock_timestamp())
            """,
            (request_id, tenant_id, job_id, note, actor_id),
        )
        for position, (product_id, uom_id, quantity) in enumerate(checked.value, start=1):
            self._connection.execute(
                """
                INSERT INTO maintenance.part_request_lines (id, tenant_id, request_id, product_id, uom_id, quantity, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, request_id, product_id, uom_id, quantity, position),
            )
        self._event(tenant_id, job_id, actor_id, "parts_requested", {"request_id": request_id, "lines": len(checked.value), "note": note})
        self._audit(
            tenant_id, actor_id, request_id, "part_request.created",
            {"job_id": job_id, "lines": [{"product_id": p, "uom_id": u, "quantity": float(q)} for p, u, q in checked.value]},
        )
        notifications.notify_parts(
            self._connection,
            tenant_id=tenant_id,
            user_ids=notifications.supervisors(self._connection, tenant_id),
            kind=notifications.PARTS_REQUESTED,
            number=number,
            equipment_name=equipment_name,
            body=note,
        )
        return Ok(request_id)

    def _checked_request_lines(self, tenant_id: str, lines: list[dict]) -> Result[list[tuple[str, str, Decimal]]]:
        """Every line checked before anything is written: a positive quantity of a product
        of this tenant, in that product's own unit (stock is counted and issued in it),
        whole for a whole-count unit."""
        if not lines:
            return Err("INVALID_LINES", "a parts request needs at least one line", "une demande de pièces doit comporter au moins une ligne")
        core = CoreService(self._connection)
        checked: list[tuple[str, str, Decimal]] = []
        for line in lines:
            quantity = _decimal(line.get("quantity"))
            if quantity is None or quantity <= _ZERO:
                return Err("INVALID_QUANTITY", "every quantity must be positive", "chaque quantité doit être positive")
            product_id = line.get("product_id") or ""
            uom = core.get_product_uom(tenant_id, product_id)
            if uom is None:
                return Err("UNKNOWN_PRODUCT", f"product {product_id} not found", f"article {product_id} introuvable")
            if line.get("uom_id") != uom.id:
                return Err(
                    "UOM_MISMATCH",
                    f"parts are requested in the product's own unit ({uom.code})",
                    f"les pièces se demandent dans l'unité de l'article ({uom.code})",
                )
            whole = validate_quantity_for_uom(float(quantity), uom)
            if isinstance(whole, Err):
                return whole
            checked.append((product_id, uom.id, quantity))
        return Ok(checked)

    # ---- availability ------------------------------------------------------------------

    def availability(self, tenant_id: str, request_id: str) -> dict | None:
        """Per line, every location holding some of its product that may be promised:
        `available = on hand - reserved`, blocked (quarantine) locations left out, only
        locations with something available, by name. `in_spare_parts` marks the
        spare-parts location and the ones under it, which the approval puts first.
        None when there is no such request."""
        request = self._request(tenant_id, request_id)
        if request is None:
            return None
        lines = self._lines(tenant_id, request_id)
        products = {line.product_id for line in lines}

        available_by_product: dict[str, list[tuple[str, Decimal]]] = {}
        for level in StockService(self._connection).list_stock_items(tenant_id):
            if level.product_id not in products:
                continue
            # Each side through its own text, so float noise from the subtraction never shows.
            available = (_decimal(level.quantity_on_hand) or _ZERO) - (_decimal(level.quantity_reserved) or _ZERO)
            if available > _ZERO:
                available_by_product.setdefault(level.product_id, []).append((level.location_id, available))

        location_ids = sorted({location_id for found in available_by_product.values() for location_id, _ in found})
        locations = {
            location.id: location
            for location in LocationService(self._connection).get_locations_by_ids(tenant_id=tenant_id, location_ids=location_ids)
        }

        spare = SparePartsService(self._connection).spare_locations(tenant_id)
        result_lines = []
        for line in lines:
            offered = [
                {
                    "location_id": location_id,
                    "location_name": locations[location_id].name,
                    "available": float(available),
                    "in_spare_parts": location_id in spare,
                }
                for location_id, available in available_by_product.get(line.product_id, [])
                if location_id in locations and not locations[location_id].is_blocked
            ]
            offered.sort(key=lambda entry: (entry["location_name"].casefold(), entry["location_id"]))
            result_lines.append({"line_id": line.id, "product_id": line.product_id, "locations": offered})
        return {"lines": result_lines}

    # ---- decide --------------------------------------------------------------------------

    def approve(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        request_id: str,
        lines: list[dict],
        note: str | None,
        correlation_id: str,
    ) -> Result[None]:
        """Decides a pending request. `lines` are `{line_id, location_id, issue_quantity}`,
        one per line of the request: the quantity issued now from `location_id` (needed
        when it is above zero), the rest of the line goes to purchase.

        Every line is checked first; only then is stock issued, the split stored, the
        remainder published for procurement (purchase lines only) and the requester told.
        Any refusal returns before the first write.
        """
        request = self._request(tenant_id, request_id, lock=True)
        if request is None:
            return _request_not_found(request_id)
        if request.status != "pending":
            return self._already_decided(request.status)
        # FOR SHARE: a cancel or close of the job (which locks it FOR UPDATE) waits for this decision.
        job_status = self._connection.execute(
            "SELECT status FROM maintenance.jobs WHERE id = %s FOR SHARE", (request.job_id,)
        ).fetchone()[0]
        if job_status in _CLOSED_JOB_STATUSES:
            # Nothing leaves the warehouse for a job that is over; the request can still be refused.
            return Err(
                "INVALID_TRANSITION",
                f"the job is {job_status}: refuse this request instead",
                "l'intervention est clôturée ou annulée : refusez plutôt cette demande",
            )
        request_lines = self._lines(tenant_id, request_id)

        decisions = self._checked_decisions(tenant_id, request_lines, lines)
        if isinstance(decisions, Err):
            return decisions

        # Nothing has been written yet. From here on every check has passed.
        stock = StockService(self._connection)
        reference = f"maintenance:{request.job_number}"
        for decision in decisions.value:
            if decision.issue > _ZERO:
                issued = stock.issue_stock(
                    tenant_id=tenant_id,
                    product_id=decision.line.product_id,
                    location_id=decision.location_id,
                    quantity=float(decision.issue),
                    reference=reference,
                    actor_id=actor_id,
                    move_type="maintenance",
                    respect_reservations=True,
                )
                if isinstance(issued, Err):
                    # Only reachable if the stock moved under us since the check: the caller rolls back.
                    return issued
            self._connection.execute(
                """
                UPDATE maintenance.part_request_lines
                SET location_id = %s, issued_quantity = %s, purchase_quantity = %s
                WHERE id = %s
                """,
                (decision.location_id, decision.issue, decision.purchase, decision.line.id),
            )

        to_purchase = [d for d in decisions.value if d.purchase > _ZERO]
        if to_purchase:
            publish_event(
                self._connection,
                event_type=PURCHASE_REQUESTED_EVENT,
                producer="maintenance",
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                payload={
                    "request_id": request_id,
                    "job_number": request.job_number,
                    "lines": [
                        {
                            "line_id": d.line.id,
                            "product_id": d.line.product_id,
                            "uom_id": d.line.uom_id,
                            "quantity": float(d.purchase),
                        }
                        for d in to_purchase
                    ],
                },
            )

        note = _clean(note)
        self._decide(request_id, "approved", actor_id, note)
        issued_lines = sum(1 for d in decisions.value if d.issue > _ZERO)
        self._event(
            tenant_id, request.job_id, actor_id, "parts_approved",
            {"request_id": request_id, "issued_lines": issued_lines, "purchase_lines": len(to_purchase), "note": note},
        )
        self._audit(
            tenant_id, actor_id, request_id, "part_request.approved",
            {
                "lines": [
                    {
                        "line_id": d.line.id,
                        "location_id": d.location_id,
                        "issued_quantity": float(d.issue),
                        "purchase_quantity": float(d.purchase),
                    }
                    for d in decisions.value
                ],
                "note": note,
            },
        )
        notifications.notify_parts(
            self._connection,
            tenant_id=tenant_id,
            user_ids=[request.requested_by],
            kind=notifications.PARTS_APPROVED,
            number=request.job_number,
            equipment_name=request.equipment_name,
            body=note,
        )
        return Ok(None)

    def _checked_decisions(
        self, tenant_id: str, request_lines: list[_Line], given: list[dict]
    ) -> Result[list[_Decision]]:
        """The supervisor's split of every line, all checked against each other: each line
        of the request exactly once, an issue between 0 and the line's quantity, a
        location for anything issued, whole for a whole-count unit, and no more taken
        from one location than it has available -- counting the other lines of this
        request that draw the same product from it."""
        by_id = {line.id: line for line in request_lines}
        given_ids = [entry.get("line_id") for entry in given]
        unknown = [line_id for line_id in given_ids if line_id not in by_id]
        if unknown:
            return Err(
                "UNKNOWN_LINE",
                f"line {unknown[0]} is not part of this request",
                f"la ligne {unknown[0]} ne fait pas partie de cette demande",
            )
        counts = Counter(given_ids)
        if any(count != 1 for count in counts.values()) or set(counts) != set(by_id):
            return Err(
                "LINES_INCOMPLETE",
                "every line of the request must be decided exactly once",
                "chaque ligne de la demande doit être décidée une fois et une seule",
            )

        stock = StockService(self._connection)
        core = CoreService(self._connection)
        # What is still available at (product, location), as earlier lines draw on it.
        remaining: dict[tuple[str, str], Decimal] = {}
        decisions: list[_Decision] = []
        for line in request_lines:
            entry = next(e for e in given if e.get("line_id") == line.id)
            issue = _decimal(entry.get("issue_quantity"))
            if issue is None:
                return Err("INVALID_QUANTITY", "issue_quantity must be a number", "la quantité à sortir doit être un nombre")
            location_id = _clean(entry.get("location_id"))
            if issue > _ZERO and location_id is None:
                return Err(
                    "LOCATION_REQUIRED",
                    "choose the location the parts are issued from",
                    "choisissez l'emplacement d'où sortent les pièces",
                )
            available = _ZERO
            if location_id is not None:
                key = (line.product_id, location_id)
                if key not in remaining:
                    remaining[key] = _decimal(stock.get_available_quantity(tenant_id, line.product_id, location_id)) or _ZERO
                available = remaining[key]
            split = split_line(quantity=line.quantity, issue_quantity=issue, available=available)
            if isinstance(split, Err):
                return split
            issued, purchase = split.value
            if issued > _ZERO:
                uom = core.get_product_uom(tenant_id, line.product_id)
                if uom is not None:
                    whole = validate_quantity_for_uom(float(issued), uom)
                    if isinstance(whole, Err):
                        return whole
                remaining[(line.product_id, location_id)] = available - issued
            decisions.append(
                _Decision(line=line, location_id=location_id if issued > _ZERO else None, issue=issued, purchase=purchase)
            )
        return Ok(decisions)

    def reject(self, *, tenant_id: str, actor_id: str, request_id: str, note: str | None) -> Result[None]:
        """Refuses a pending request; the note saying why is required. Nothing is issued or bought."""
        request = self._request(tenant_id, request_id, lock=True)
        if request is None:
            return _request_not_found(request_id)
        if request.status != "pending":
            return self._already_decided(request.status)
        note = _clean(note)
        if note is None:
            return Err("NOTE_REQUIRED", "say why the request is refused", "indiquez pourquoi la demande est refusée")

        self._decide(request_id, "rejected", actor_id, note)
        self._event(tenant_id, request.job_id, actor_id, "parts_rejected", {"request_id": request_id, "note": note})
        self._audit(tenant_id, actor_id, request_id, "part_request.rejected", {"note": note})
        notifications.notify_parts(
            self._connection,
            tenant_id=tenant_id,
            user_ids=[request.requested_by],
            kind=notifications.PARTS_REJECTED,
            number=request.job_number,
            equipment_name=request.equipment_name,
            body=note,
        )
        return Ok(None)

    # ---- helpers -------------------------------------------------------------------------

    def _request(self, tenant_id: str, request_id: str, *, lock: bool = False) -> _Request | None:
        # FOR UPDATE OF r: two supervisors deciding the same request at once run one after the other.
        row = self._connection.execute(
            f"""
            SELECT r.id, r.job_id, j.number, e.name, r.status, r.requested_by
            FROM maintenance.part_requests r
            JOIN maintenance.jobs j ON j.id = r.job_id
            JOIN maintenance.equipment e ON e.id = j.equipment_id
            WHERE r.id = %s AND r.tenant_id = %s
            {"FOR UPDATE OF r" if lock else ""}
            """,
            (request_id, tenant_id),
        ).fetchone()
        return _Request(*row) if row is not None else None

    def _lines(self, tenant_id: str, request_id: str) -> list[_Line]:
        rows = self._connection.execute(
            """
            SELECT id, product_id, uom_id, quantity FROM maintenance.part_request_lines
            WHERE request_id = %s AND tenant_id = %s
            ORDER BY sort_order, id
            """,
            (request_id, tenant_id),
        ).fetchall()
        return [_Line(id=r[0], product_id=r[1], uom_id=r[2], quantity=Decimal(r[3])) for r in rows]

    @staticmethod
    def _already_decided(status: str) -> Err:
        return Err(
            "ALREADY_DECIDED",
            f"this parts request is already {status}",
            "cette demande de pièces a déjà été traitée",
        )

    def _decide(self, request_id: str, status: str, actor_id: str, note: str | None) -> None:
        self._connection.execute(
            """
            UPDATE maintenance.part_requests
            SET status = %s, decided_by = %s, decided_at = clock_timestamp(), decision_note = %s
            WHERE id = %s
            """,
            (status, actor_id, note, request_id),
        )

    def _event(self, tenant_id: str, job_id: str, actor_id: str, kind: str, payload: dict) -> None:
        """One row on the job's timeline, stamped with clock_timestamp() like the job's own rows."""
        self._connection.execute(
            """
            INSERT INTO maintenance.job_events (id, tenant_id, job_id, at, actor_id, kind, payload)
            VALUES (%s, %s, %s, clock_timestamp(), %s, %s, %s)
            """,
            (str(ULID()), tenant_id, job_id, actor_id, kind, Jsonb(payload)),
        )

    def _audit(self, tenant_id: str, actor_id: str, request_id: str, action: str, payload: dict) -> None:
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type=_ENTITY,
            entity_id=request_id,
            payload=payload,
        )
