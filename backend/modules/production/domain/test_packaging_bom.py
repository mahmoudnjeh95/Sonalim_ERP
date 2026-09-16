from core.domain.result import Err, Ok
from modules.production.domain.packaging_bom import PackagingBom, PackagingBomLine, transition_bom, validate_bom_lines


def test_validate_bom_lines_rejects_empty():
    result = validate_bom_lines(())
    assert isinstance(result, Err)
    assert result.code == "EMPTY_BOM"


def test_validate_bom_lines_rejects_non_positive_quantity():
    lines = (PackagingBomLine(component_product_id="sachet", quantity_per_unit=0),)
    result = validate_bom_lines(lines)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_validate_bom_lines_accepts_positive_quantities():
    lines = (
        PackagingBomLine(component_product_id="sachet", quantity_per_unit=1),
        PackagingBomLine(component_product_id="label", quantity_per_unit=1),
    )
    result = validate_bom_lines(lines)
    assert isinstance(result, Ok)


def test_draft_to_active_succeeds():
    bom = PackagingBom(id="1", target_product_id="p1", version=1, status="draft", lines=())
    result = transition_bom(bom, "active")
    assert isinstance(result, Ok)
    assert result.value.status == "active"


def test_draft_to_archived_fails():
    bom = PackagingBom(id="1", target_product_id="p1", version=1, status="draft", lines=())
    result = transition_bom(bom, "archived")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_archived_has_no_further_transitions():
    bom = PackagingBom(id="1", target_product_id="p1", version=1, status="archived", lines=())
    result = transition_bom(bom, "active")
    assert isinstance(result, Err)
