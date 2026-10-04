import base64

import pytest
from psycopg.types.json import Jsonb

from core.domain.result import Err
from modules.production.api.shift_report_service import ShiftReportService
from modules.scan.api.scan_world import fabrication_result, make_world, ok
from modules.scan.api.session_service import MAX_PAGES, ScanSessionService

TENANT = "scan-session-test"
JPEG = {"filename": "a.jpg", "content_type": "image/jpeg", "width": 1200, "height": 1600,
        "data_base64": base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()}


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def _session(db, world, shift="Matin"):
    return ok(ScanSessionService(db).create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift=shift, default_of_id=world["of"],
    ))


def test_create_and_read_a_session(db, world):
    session = _session(db, world)
    assert (session["status"], session["shift"], session["default_of_id"]) == ("open", "Matin", world["of"])
    detail = ok(ScanSessionService(db).get_session(tenant_id=TENANT, session_id=session["id"]))
    assert detail["pages"] == [] and detail["shift_report"] is None and detail["window"] == {"start": "07:00", "end": "15:00"}
    assert detail["shift"] == "Matin"
    [listed] = ScanSessionService(db).list_sessions(tenant_id=TENANT)
    assert listed["page_count"] == 0 and "review_state" not in listed


def test_only_known_shifts_and_shift_fiches(db, world):
    service = ScanSessionService(db)
    common = dict(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], default_of_id=None)
    assert service.create_session(kind="shift", shift="Brunch", **common).code == "UNKNOWN_SHIFT"
    assert service.create_session(kind="qc", shift="Matin", **common).code == "NOT_SUPPORTED_YET"


def test_pages_are_queued_and_their_image_kept(db, world):
    service = ScanSessionService(db)
    session = _session(db, world)
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    assert (page["status"], page["width"], page["attribution"]) == ("queued", 1200, None)
    image, content_type = ok(service.page_image(tenant_id=TENANT, page_id=page["id"]))
    assert image == b"\xff\xd8\xff fake jpeg" and content_type == "image/jpeg"
    assert service.page_image(tenant_id="another-tenant", page_id=page["id"]).code == "NOT_FOUND"


def test_upload_limits(db, world):
    service = ScanSessionService(db)
    session_id = _session(db, world)["id"]
    add = lambda files: service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=files)  # noqa: E731
    assert add([{**JPEG, "content_type": "image/heic"}]).code == "UNSUPPORTED_IMAGE"
    assert add([{**JPEG, "data_base64": "not base64!"}]).code == "UNSUPPORTED_IMAGE"
    big = base64.b64encode(b"0" * (10 * 1024 * 1024 + 1)).decode()
    assert add([{**JPEG, "data_base64": big}]).code == "IMAGE_TOO_LARGE"
    assert add([JPEG] * (MAX_PAGES + 1)).code == "TOO_MANY_PAGES"


def test_a_read_page_is_matched_to_the_shift(db, world):
    service = ScanSessionService(db)
    session = _session(db, world)
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    db.execute(
        "UPDATE scan.scan_pages SET status = 'read', form_type = 'fabrication', ocr_result = %s WHERE id = %s",
        (Jsonb(fabrication_result(hours="A 15H")), page["id"]),
    )
    [summary] = ok(service.get_session(tenant_id=TENANT, session_id=session["id"]))["pages"]
    assert summary["attribution"]["verdict"] == "other_shift" and summary["attribution"]["reasons"] == ["hours"]


def test_delete_reread_and_discard(db, world):
    service = ScanSessionService(db)
    session_id = _session(db, world)["id"]
    [first, second] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG, JPEG]))
    ok(service.delete_page(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, page_id=first["id"]))
    db.execute("UPDATE scan.scan_pages SET status = 'failed', attempts = 3, error = 'down' WHERE id = %s", (second["id"],))
    reread = ok(service.reread_page(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, page_id=second["id"], form_hint="conditionnement"))
    assert (reread["status"], reread["attempts"], reread["error"], reread["form_hint"]) == ("queued", 0, None, "conditionnement")
    assert service.reread_page(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, page_id=second["id"], form_hint="menu").code == "INVALID_VALUE"
    ok(service.discard_session(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id))
    refused = service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG])
    assert isinstance(refused, Err) and refused.code == "SESSION_CLOSED"


def test_the_shift_state_shows_existing_sections(db, world):
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    ok(reports.save_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops",
                            payload={"stops": [{"started_at": "2030-03-04T08:00", "note": "x"}]}))
    session = _session(db, world)
    shift = ok(ScanSessionService(db).get_session(tenant_id=TENANT, session_id=session["id"]))["shift_report"]
    assert shift["id"] == shift_id
    assert (shift["sections"]["stops"]["status"], shift["sections"]["stops"]["rows"]) == ("draft", 1)
    assert shift["sections"]["runs"]["rows"] == 0 and len(shift["sections"]["stops"]["fingerprint"]) == 16


def test_audit_rows_for_session_changes(db, world):
    service = ScanSessionService(db)
    session_id = _session(db, world)["id"]
    ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG]))
    actions = {r[0] for r in db.execute("SELECT action FROM core.audit_log WHERE tenant_id = %s", (TENANT,)).fetchall()}
    assert {"scan_session.created", "scan_session.pages_added"} <= actions


def test_create_session_refuses_a_validated_shift(db, world):
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(
        tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin",
    ))["id"]
    db.execute("UPDATE production.shift_reports SET status = 'validated' WHERE id = %s", (shift_id,))
    refused = ScanSessionService(db).create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift="Matin", default_of_id=world["of"],
    )
    assert isinstance(refused, Err) and refused.code == "SHIFT_VALIDATED"


def test_shift_state_is_absent_when_the_production_service_refuses(db, world, monkeypatch):
    reports = ShiftReportService(db)
    ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))
    monkeypatch.setattr(ShiftReportService, "get_shift", lambda self, **kwargs: Err("NOT_FOUND", "x", "x"))
    session = _session(db, world)
    detail = ok(ScanSessionService(db).get_session(tenant_id=TENANT, session_id=session["id"]))
    assert detail["shift_report"] is None


def test_shift_pages_lists_only_the_applied_sessions_pages(db, world):
    service = ScanSessionService(db)
    session = _session(db, world)
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session["id"], files=[JPEG]))
    shift_report_id = "some-shift-report-id"
    db.execute(
        "UPDATE scan.scan_sessions SET status = 'applied', shift_report_id = %s WHERE id = %s",
        (shift_report_id, session["id"]),
    )
    [listed] = service.shift_pages(tenant_id=TENANT, shift_report_id=shift_report_id)
    assert listed["id"] == page["id"] and "form_type" in listed
    assert service.shift_pages(tenant_id="another-tenant", shift_report_id=shift_report_id) == []
    other_session = _session(db, world, shift="Soir")
    db.execute(
        "UPDATE scan.scan_sessions SET shift_report_id = %s WHERE id = %s",
        (shift_report_id, other_session["id"]),
    )
    assert service.shift_pages(tenant_id=TENANT, shift_report_id=shift_report_id) == [listed]
