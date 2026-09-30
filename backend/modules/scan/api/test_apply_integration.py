import base64

import pytest
from psycopg.types.json import Jsonb

from modules.production.api.shift_report_service import ShiftReportService
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.scan_world import fabrication_result, make_world, ok
from modules.scan.api.session_service import ScanSessionService
from modules.scan.domain.review import APPLY_ORDER

TENANT = "scan-apply-test"
ALL = set(APPLY_ORDER)
JPEG = {"filename": "a.jpg", "content_type": "image/jpeg", "data_base64": base64.b64encode(b"\xff\xd8 x").decode()}


@pytest.fixture
def world(db):
    return make_world(db, TENANT)


def _reviewed(db, world):
    """A session with one read fabrication page, and the review a user would send."""
    service = ScanSessionService(db)
    session_id = ok(service.create_session(
        tenant_id=TENANT, actor_id=world["actor"], kind="shift", work_center_id=world["work_center"],
        report_date=world["day"], shift="Matin", default_of_id=world["of"],
    ))["id"]
    [page] = ok(service.add_pages(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, files=[JPEG]))
    db.execute("UPDATE scan.scan_pages SET status = 'read', form_type = 'fabrication', ocr_result = %s WHERE id = %s",
               (Jsonb(fabrication_result()), page["id"]))
    body = ok(service.proposal(tenant_id=TENANT, session_id=session_id))
    sections = body["proposal"]["sections"]
    sections["waste_production"]["waste_lines"][0]["category"] = "raw_material"  # the user picks the kind
    fingerprints = {k: v["fingerprint"] for k, v in (body["shift"] or {}).get("sections", {}).items()}
    return service, session_id, body["proposal"]["header"], sections, fingerprints


def _apply(service, world, session_id, header, sections, fingerprints, allowed=ALL):
    return service.apply(tenant_id=TENANT, actor_id=world["actor"], session_id=session_id, header=header,
                         sections=sections, fingerprints=fingerprints, allowed_sections=allowed)


def test_apply_writes_drafts_and_closes_the_session(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    result = ok(_apply(service, world, session_id, header, sections, fingerprints))
    assert result["sections_written"] == ["runs", "waste_production", "stops"]
    shift = ok(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=result["shift_report_id"]))
    states = {s["key"]: s for s in shift["sections"]}
    assert states["runs"]["status"] == "draft" and states["runs"]["payload"]["runs"][0]["lot_number"] == "D0063SNL"
    assert states["stops"]["payload"]["stops"][0]["note"] == "coupure"
    assert shift["conducteur"] == "Conducteur Un"
    session = ok(service.get_session(tenant_id=TENANT, session_id=session_id))
    assert (session["status"], session["shift_report_id"]) == ("applied", result["shift_report_id"])
    assert db.execute("SELECT count(*) FROM scan.scan_field_outcomes WHERE session_id = %s", (session_id,)).fetchone()[0] > 0
    assert db.execute("SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'scan_session.applied'", (TENANT,)).fetchone()[0] == 1


def test_apply_learns_the_codes_the_user_corrected(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    ok(_apply(service, world, session_id, header, sections, fingerprints))
    assert ScanAliasService(db).alias_map(tenant_id=TENANT)[("waste_production", "dechet semoule")] == "raw_material"


def test_a_section_the_save_refuses_names_itself(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    sections["waste_production"]["waste_lines"][0]["category"] = None
    refused = _apply(service, world, session_id, header, sections, fingerprints)
    assert refused.code == "INVALID_VALUE" and refused.message.startswith("waste_production:")


def test_apply_refuses_a_section_changed_since_review(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    ok(reports.save_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops",
                            payload={"stops": [{"started_at": "2030-03-04T08:00", "note": "typed by the team"}]}))
    refused = _apply(service, world, session_id, header, sections, fingerprints)
    assert refused.code == "SECTION_CHANGED" and "stops" in refused.message


def test_apply_never_writes_a_validated_shift(db, world):
    service, session_id, header, sections, _ = _reviewed(db, world)
    shift_id = ok(ShiftReportService(db).open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    db.execute("UPDATE production.shift_reports SET status = 'validated' WHERE id = %s", (shift_id,))
    assert _apply(service, world, session_id, header, sections, {}).code == "SHIFT_VALIDATED"


def test_apply_needs_each_sections_right(db, world):
    service, session_id, header, sections, fingerprints = _reviewed(db, world)
    refused = _apply(service, world, session_id, header, sections, fingerprints, allowed={"runs", "stops"})
    assert refused.code == "FORBIDDEN_SECTION" and "waste_production" in refused.message


def test_a_submitted_section_is_replaced_with_a_revision(db, world):
    service, session_id, header, sections, _ = _reviewed(db, world)
    reports = ShiftReportService(db)
    shift_id = ok(reports.open_shift(tenant_id=TENANT, actor_id=world["actor"], work_center_id=world["work_center"], report_date=world["day"], shift="Matin"))["id"]
    ok(reports.save_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops",
                            payload={"stops": [{"started_at": "2030-03-04T08:00", "note": "old"}]}))
    ok(reports.submit_section(tenant_id=TENANT, actor_id=world["actor"], shift_report_id=shift_id, section_key="stops"))
    fingerprints = {k: v["fingerprint"] for k, v in ok(service.proposal(tenant_id=TENANT, session_id=session_id))["shift"]["sections"].items()}
    ok(_apply(service, world, session_id, header, {"stops": sections["stops"]}, fingerprints))
    stops = next(s for s in ok(reports.get_shift(tenant_id=TENANT, shift_report_id=shift_id))["sections"] if s["key"] == "stops")
    assert (stops["status"], stops["revised_after_submit"], stops["payload"]["stops"][0]["note"]) == ("submitted", True, "coupure")


def test_nothing_to_apply(db, world):
    service, session_id, header, _, _ = _reviewed(db, world)
    assert _apply(service, world, session_id, header, {}, {}).code == "NOTHING_TO_APPLY"
    assert _apply(service, world, session_id, header, {"energy": {}}, {}).code == "INVALID_SECTION"
