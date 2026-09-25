from core.domain.result import Err, Ok
from modules.production.api.work_center_service import WorkCenterService


def test_a_work_center_is_a_production_line_unless_tagged_grinder(db):
    service = WorkCenterService(db)
    line = service.create_work_center(tenant_id="t-line-type", actor_id="u1", code="L1", name="Line 1")
    grinder = service.create_work_center(tenant_id="t-line-type", actor_id="u1", code="R1", name="Broyeur", line_type="grinder")
    assert isinstance(line, Ok) and line.value.line_type == "production"
    assert isinstance(grinder, Ok) and grinder.value.line_type == "grinder"

    listed = {wc.code: wc.line_type for wc in service.list_work_centers(tenant_id="t-line-type")}
    assert listed == {"L1": "production", "R1": "grinder"}


def test_the_line_type_can_be_changed_and_is_validated(db):
    service = WorkCenterService(db)
    created = service.create_work_center(tenant_id="t-line-type", actor_id="u1", code="L2", name="Line 2")
    assert isinstance(created, Ok)

    updated = service.update_work_center(tenant_id="t-line-type", actor_id="u1", work_center_id=created.value.id, line_type="grinder")
    assert isinstance(updated, Ok) and updated.value.line_type == "grinder"
    assert updated.value.name == "Line 2"

    rejected = service.update_work_center(tenant_id="t-line-type", actor_id="u1", work_center_id=created.value.id, line_type="oven")
    assert isinstance(rejected, Err) and rejected.code == "INVALID_LINE_TYPE"
