"""The scan schema exists once migrations have run, and its permissions reach the catalog."""
from __future__ import annotations

from core.permissions_registry import permission_catalog


def _columns(db, table: str) -> set[str]:
    rows = db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'scan' AND table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def test_scan_tables_exist(db):
    assert {"id", "tenant_id", "kind", "work_center_id", "report_date", "shift", "default_of_id",
            "shift_report_id", "status", "review_state", "created_by", "applied_at"} <= _columns(db, "scan_sessions")
    assert {"id", "tenant_id", "session_id", "image", "content_type", "status", "attempts", "form_hint",
            "form_type", "rotation", "ocr_result", "error", "read_at"} <= _columns(db, "scan_pages")
    assert {"tenant_id", "kind", "raw_text_normalized", "raw_text_example", "target_value", "use_count"} <= _columns(db, "scan_aliases")
    assert {"session_id", "field_path", "read_text", "proposed_value", "final_value", "changed"} <= _columns(db, "scan_field_outcomes")


def test_scan_permissions_are_in_the_catalog():
    codes = {entry["permission"] for entry in permission_catalog() if entry["module"] == "scan"}
    assert codes == {"scan.use_scanner", "scan.view_scans", "scan.admin_aliases"}
