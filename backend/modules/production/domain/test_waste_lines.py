"""The déchet list's rules, without a database.

Waste used to be a fixed column per category, which meant the plant could not
record scotch at all and no figure said which item it counted -- so a screen had
to borrow a unit from whatever product looked closest. These tests pin the
replacement: a line names its item, its stage belongs to its report type, and
nothing here ever adds two items together.
"""
from __future__ import annotations

from core.domain.result import Err, Ok
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    SemolinaLine,
    WasteLine,
    validate_conditionnement_detail,
    validate_conditionnement_stock_targets,
    validate_daily_detail,
    validate_daily_stock_targets,
    validate_waste_lines,
    validate_waste_products,
    waste_total_by_category,
)


def test_a_daily_report_may_lose_material_before_and_at_the_press():
    lines = (
        WasteLine(category="raw_material", product_id="semoule", quantity=5),
        WasteLine(category="press", product_id="rebut", quantity=3),
    )
    assert isinstance(validate_waste_lines(lines, report_type="daily"), Ok)


def test_a_daily_report_may_also_lose_material_at_cross_kneading_and_conditioning():
    """découpe was renamed to "Cross", and pétrin / finished-product-at-
    conditioning joined it as daily-report stages."""
    lines = (
        WasteLine(category="cross", product_id="semoule", quantity=1),
        WasteLine(category="kneading", product_id="pate", quantity=2),
        WasteLine(category="finished_product_conditioning", product_id="spaghetti", quantity=3),
    )
    assert isinstance(validate_waste_lines(lines, report_type="daily"), Ok)


def test_cutting_is_no_longer_a_valid_daily_category():
    """The old name the plant used before the rename is refused, exactly like
    any other category a daily report never had."""
    lines = (WasteLine(category="cutting", product_id="semoule", quantity=1),)
    result = validate_waste_lines(lines, report_type="daily")
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_a_packing_report_may_lose_product_and_packaging():
    lines = (
        WasteLine(category="product", product_id="spaghetti", quantity=2),
        WasteLine(category="packaging", product_id="scotch", quantity=1),
    )
    assert isinstance(validate_waste_lines(lines, report_type="conditionnement"), Ok)


def test_a_packing_report_cannot_claim_waste_from_a_stage_it_never_ran():
    """Packing does not run the press. Allowing it would land the figure in the
    OF's raw-material total, where nobody would ever question it."""
    lines = (WasteLine(category="press", product_id="rebut", quantity=3),)
    result = validate_waste_lines(lines, report_type="conditionnement")
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_a_daily_report_cannot_claim_packaging_waste():
    lines = (WasteLine(category="packaging", product_id="film", quantity=1),)
    result = validate_waste_lines(lines, report_type="daily")
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_an_invented_category_is_refused():
    lines = (WasteLine(category="atelier", product_id="x", quantity=1),)
    assert isinstance(validate_waste_lines(lines, report_type="daily"), Err)


def test_a_negative_quantity_is_not_waste():
    lines = (WasteLine(category="press", product_id="rebut", quantity=-1),)
    result = validate_waste_lines(lines, report_type="daily")
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_no_waste_at_all_is_a_perfectly_good_report():
    assert isinstance(validate_waste_lines((), report_type="daily"), Ok)


def test_a_draft_may_have_a_quantity_before_it_has_an_item():
    """A team typing at the end of a shift should not be stopped mid-thought.
    Completeness is demanded when the report leaves them, not before."""
    lines = (WasteLine(category="press", quantity=3),)
    assert isinstance(validate_waste_lines(lines, report_type="daily"), Ok)
    assert isinstance(validate_daily_detail(DailyReportDetail(waste_lines=lines)), Ok)


def test_submitting_a_quantity_with_no_item_is_refused():
    """The validator has no way to judge "3" -- three kilos or three cartons?"""
    lines = (WasteLine(category="press", quantity=3),)
    result = validate_waste_products(lines)
    assert isinstance(result, Err)
    assert result.code == "MISSING_WASTE_PRODUCT"


def test_a_blank_item_counts_as_no_item():
    result = validate_waste_products((WasteLine(category="press", product_id="   ", quantity=3),))
    assert isinstance(result, Err)


def test_a_line_at_zero_needs_no_item():
    """An untouched row in a form recorded nothing, so there is nothing to name."""
    assert isinstance(validate_waste_products((WasteLine(category="press", quantity=0),)), Ok)


def test_the_daily_submit_check_covers_the_waste_list():
    detail = DailyReportDetail(
        semolina_lines=(SemolinaLine(product_id="semoule", quantity=100, location_id="store"),),
        raw_material_location_id="store",
        waste_lines=(WasteLine(category="press", quantity=3),),
    )
    result = validate_daily_stock_targets(detail)
    assert isinstance(result, Err)
    assert result.code == "MISSING_WASTE_PRODUCT"


def test_the_packing_submit_check_covers_the_waste_list():
    detail = ConditionnementReportDetail(
        finished_product_quantity=100,
        finished_goods_location_id="store",
        waste_lines=(WasteLine(category="packaging", quantity=2),),
    )
    result = validate_conditionnement_stock_targets(detail)
    assert isinstance(result, Err)
    assert result.code == "MISSING_WASTE_PRODUCT"


def test_the_detail_validators_reject_a_wrong_category():
    daily = DailyReportDetail(waste_lines=(WasteLine(category="product", product_id="x", quantity=1),))
    assert isinstance(validate_daily_detail(daily), Err)

    packing = ConditionnementReportDetail(
        waste_lines=(WasteLine(category="raw_material", product_id="x", quantity=1),)
    )
    assert isinstance(validate_conditionnement_detail(packing), Err)


def test_the_same_item_twice_in_one_category_is_two_events():
    """Two spills of the same film at different hours are two facts with two
    notes. Merging them at entry would lose what tells them apart."""
    lines = (
        WasteLine(category="packaging", product_id="film", quantity=1.5, note="reel change"),
        WasteLine(category="packaging", product_id="film", quantity=2.5, note="seal fault"),
    )
    assert isinstance(validate_waste_lines(lines, report_type="conditionnement"), Ok)
    assert waste_total_by_category(lines) == {"packaging": 4.0}


def test_totals_are_per_stage_and_never_across_them():
    """There is no grand total on purpose: kilos of dough and counts of cartons
    do not add up to anything a person can read."""
    lines = (
        WasteLine(category="raw_material", product_id="semoule", quantity=5),
        WasteLine(category="press", product_id="rebut", quantity=3),
        WasteLine(category="press", product_id="rebut", quantity=2),
    )
    assert waste_total_by_category(lines) == {"raw_material": 5.0, "press": 5.0}


def test_no_lines_means_no_categories_rather_than_zeroes():
    """An empty dict says nothing was lost. A dict of zeroes would claim every
    stage was checked and found clean, which no one reported."""
    assert waste_total_by_category(()) == {}


# --- the plant's own waste types --------------------------------------------
#
# A tenant adds kinds of its own (an id in production.waste_types, entered on one
# report). This module reads no database, so the caller passes the ids for the
# report type being checked and the rules stay the same closed set.


def test_a_plants_own_waste_type_is_accepted_on_the_report_it_belongs_to():
    lines = (WasteLine(category="01PFFAB", product_id="pate", quantity=2),)
    result = validate_waste_lines(lines, report_type="daily", custom_categories=frozenset({"01PFFAB"}))
    assert isinstance(result, Ok)


def test_a_plants_own_waste_type_is_not_valid_unless_the_caller_vouches_for_it():
    """The caller passes only the ids that belong to this report type, so a type
    entered on the daily report is refused on a packing report: it describes a
    stage that report never ran."""
    lines = (WasteLine(category="01PFFAB", product_id="pate", quantity=2),)
    result = validate_waste_lines(lines, report_type="conditionnement", custom_categories=frozenset())
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_a_plants_own_types_do_not_open_the_door_to_typos():
    lines = (WasteLine(category="atelier", product_id="x", quantity=1),)
    result = validate_waste_lines(lines, report_type="daily", custom_categories=frozenset({"01PFFAB"}))
    assert isinstance(result, Err)
    assert result.code == "INVALID_WASTE_CATEGORY"


def test_built_in_categories_still_work_alongside_the_plants_own():
    lines = (
        WasteLine(category="press", product_id="rebut", quantity=1),
        WasteLine(category="01PFFAB", product_id="pate", quantity=2),
    )
    assert isinstance(
        validate_waste_lines(lines, report_type="daily", custom_categories=frozenset({"01PFFAB"})), Ok
    )


def test_the_detail_validators_pass_the_plants_types_through():
    daily = DailyReportDetail(waste_lines=(WasteLine(category="01PFFAB", product_id="pate", quantity=2),))
    assert isinstance(validate_daily_detail(daily), Err)
    assert isinstance(validate_daily_detail(daily, waste_categories=frozenset({"01PFFAB"})), Ok)

    packing = ConditionnementReportDetail(waste_lines=(WasteLine(category="01CELLO", product_id="film", quantity=2),))
    assert isinstance(validate_conditionnement_detail(packing), Err)
    assert isinstance(validate_conditionnement_detail(packing, waste_categories=frozenset({"01CELLO"})), Ok)
