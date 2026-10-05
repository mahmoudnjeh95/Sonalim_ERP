import base64

import pytest
from psycopg.types.json import Jsonb

from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.scan_world import fabrication_result, make_world, ok
from modules.scan.api.session_service import ScanSessionService

TENANT = "scan-proposal-test"
JPEG = {"filename": "a.jpg", "content_type": "image/jpeg", "data_base64": base64.b64encode(b"\xff\xd8 x").decode()}


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def _session_with_page(db, world, result):
    service = ScanSessionService(db)
    session = ok(service.create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift="Matin", default_of_id=world["of"],
    ))
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    db.execute(
        "UPDATE scan.scan_pages SET status = 'read', form_type = %s, ocr_result = %s WHERE id = %s",
        (result["form_type"], Jsonb(result), page["id"]),
    )
    return service, session["id"], page["id"]


def test_the_proposal_uses_the_plants_names_and_the_default_of(db, world):
    service, session_id, _ = _session_with_page(db, world, fabrication_result())
    body = ok(service.proposal(tenant_id=TENANT, session_id=session_id))
    proposal = body["proposal"]
    [run] = proposal["sections"]["runs"]["runs"]
    assert (run["of_id"], run["lot_number"], run["production_minutes"]) == (world["of"], "D0063SNL", 420)
    [versement] = proposal["sections"]["runs"]["versements"]
    assert (versement["product_id"], versement["quantity"]) == (world["semoule"], 3.25)
    assert proposal["header"]["conducteur"] == "Conducteur Un"
    assert body["shift"] is None and body["review_state"] == {}


def test_a_learned_alias_is_used_by_the_next_proposal(db, world):
    service, session_id, _ = _session_with_page(db, world, fabrication_result())
    ScanAliasService(db).learn(tenant_id=TENANT, actor_id=world["actor"], kind="waste_production", read_text="Déchet semoule", target_value="raw_material")
    [line] = ok(service.proposal(tenant_id=TENANT, session_id=session_id))["proposal"]["sections"]["waste_production"]["waste_lines"]
    assert line["category"] == "raw_material"


def test_an_other_shift_page_is_included_through_the_review_state(db, world):
    service, session_id, page_id = _session_with_page(db, world, fabrication_result(hours="A 15H"))
    assert ok(service.proposal(tenant_id=TENANT, session_id=session_id))["proposal"]["sections"] == {}
    ok(service.save_review(tenant_id=TENANT, session_id=session_id, review_state={"include_pages": [page_id]}))
    body = ok(service.proposal(tenant_id=TENANT, session_id=session_id))
    assert "runs" in body["proposal"]["sections"] and body["review_state"] == {"include_pages": [page_id]}
