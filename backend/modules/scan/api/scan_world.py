"""A tenant with a PC line, its shifts, products and an open OF, for the scan integration tests."""
from __future__ import annotations

import datetime

from ulid import ULID

from core.domain.result import Ok
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.service import WorkOrderService

DAY = datetime.date(2030, 3, 4)  # lot D0063SNL: team D, year digit 0, day 63


def ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def make_world(db, tenant: str) -> dict:
    actor, uom, pasta, semoule, film, work_center, location = (str(ULID()) for _ in range(7))
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, tenant, f"{actor}@test.local"))
    db.execute("INSERT INTO core.uoms (id, tenant_id, code, name, category) VALUES (%s, %s, 'kg', 'Kilogram', 'weight')", (uom, tenant))
    for product_id, sku, name in ((pasta, "SC-VERM", "Vermicelle 500g PC"), (semoule, "SC-SSSE", "Semoule SSSE"), (film, "SC-FILM", "Film Active PC")):
        db.execute("INSERT INTO core.products (id, tenant_id, sku, name, uom_id) VALUES (%s, %s, %s, %s, %s)", (product_id, tenant, sku, name, uom))
    db.execute("INSERT INTO warehouse.locations (id, tenant_id, code, name) VALUES (%s, %s, 'SC-LOC', 'Store')", (location, tenant))
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = ANY(%s)", (location, [pasta, semoule, film]))
    db.execute("UPDATE core.products SET net_weight_grams = 500, packets_per_carton = 12 WHERE id = %s", (pasta,))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SC-PC', 'Ligne PC')", (work_center, tenant))
    for shift, start, end in (("Matin", "07:00", "15:00"), ("Soir", "15:00", "23:00"), ("Nuit", "23:00", "07:00")):
        db.execute(
            "INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, %s, %s, %s)",
            (tenant, shift, start, end),
        )
    classes = ProductClassificationService(db)
    ok(classes.set_classification(tenant_id=tenant, actor_id=actor, product_id=pasta, category="finished_good", packaging_format="packet"))
    ok(classes.set_classification(tenant_id=tenant, actor_id=actor, product_id=semoule, category="raw_material"))
    ok(classes.set_classification(tenant_id=tenant, actor_id=actor, product_id=film, category="packaging_component", packaging_kind="film"))
    orders = WorkOrderService(db)
    of_id = ok(orders.create_work_order(
        tenant_id=tenant, actor_id=actor, product_id=pasta, planned_quantity=1000, work_center_id=work_center, start_date=DAY,
    )).id
    ok(orders.start_work_order(tenant_id=tenant, actor_id=actor, work_order_id=of_id))
    return {"tenant": tenant, "actor": actor, "pasta": pasta, "semoule": semoule, "film": film,
            "work_center": work_center, "of": of_id, "day": DAY}


def fabrication_result(date: str = "04/03/2030", hours: str = "D 07 H") -> dict:
    """What the OCR container returns for a small fabrication fiche of DAY."""
    def cell(text: str) -> dict:
        return {"text": text, "confidence": 0.9, "box": [0.1, 0.1, 0.2, 0.2]}

    return {
        "form_type": "fabrication", "form_confidence": 0.8, "rotation": 0, "accept_score": 0.5,
        "header": {"date": cell(date), "team_hours": cell(hours), "line_pc": cell("x"), "conducteur": cell("Conducteur Un")},
        "blocks": [
            {"key": "production", "found": True, "rows": [{"cells": {
                "lot": cell("D0063SNL"), "start": cell("07h00"), "end": cell("14h00"),
                "sem_origin": cell("SC-SSSE"), "sem_tonnes": cell("3,25"), "water": cell("28,9"),
            }}]},
            {"key": "stops", "found": True, "rows": [{"cells": {"panne": cell("coupure"), "start": cell("12h18"), "end": cell("12h37")}}]},
            {"key": "waste_petrin", "found": True, "rows": [{"cells": {"quantity": cell("1,47"), "cause": cell("Déchet semoule")}}]},
        ],
    }
