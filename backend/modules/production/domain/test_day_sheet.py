from __future__ import annotations

import pytest

from modules.production.domain.day_sheet import DailyFact, PackingFact, build_rows


def _rows(daily=(), packing=(), **kwargs):
    return {(r.key, r.ref): r for r in build_rows(list(daily), list(packing), **kwargs)}


def test_an_empty_day_still_prints_the_fixed_rows_with_nothing_in_them():
    rows = _rows()
    assert {"total_mp", "regrind", "total_fab", "water", "production_hours", "total_waste", "total_finished"} <= {
        key for key, _ in rows
    }
    assert all(row.by_column == {} and row.total is None for row in rows.values())


def test_the_rows_that_exist_once_per_product_or_kind_only_appear_when_something_was_reported():
    rows = _rows()
    assert not [key for key, _ in rows if key in {"semolina", "waste", "finished", "packing_waste", "packed_product_waste"}]


def test_total_mp_adds_the_qualities_and_total_fab_adds_the_rebroyat_to_it():
    rows = _rows(
        daily=[
            DailyFact(
                column="morning",
                regrind_t=1.15,
                semolina=(("salem", "S. Salem", 11.1), ("extra", "S. Extra fine", 0.75)),
            )
        ]
    )
    assert rows[("semolina", "salem")].by_column == {"morning": pytest.approx(11.1)}
    assert rows[("total_mp", None)].by_column == {"morning": pytest.approx(11.85)}
    assert rows[("total_fab", None)].by_column == {"morning": pytest.approx(13.0)}
    assert rows[("total_fab", None)].total == pytest.approx(13.0)


def test_a_quality_poured_in_two_shifts_is_one_row_with_a_cell_per_shift_and_a_total():
    rows = _rows(
        daily=[
            DailyFact(column="morning", semolina=(("salem", "S. Salem", 10.0),)),
            DailyFact(column="night", semolina=(("salem", "S. Salem", 4.0),)),
        ]
    )
    row = rows[("semolina", "salem")]
    assert row.by_column == {"morning": 10.0, "night": 4.0}
    assert row.total == 14.0


def test_two_reports_in_one_shift_are_added_into_the_same_cell():
    rows = _rows(daily=[DailyFact(column="morning", water_l=100), DailyFact(column="morning", water_l=50)])
    assert rows[("water", None)].by_column == {"morning": 150}


def test_a_shift_that_reported_zero_is_a_zero_cell_and_a_shift_with_no_report_has_no_cell():
    rows = _rows(daily=[DailyFact(column="morning", water_l=0)], packing=[PackingFact(column="night")])
    assert rows[("water", None)].by_column == {"morning": 0.0}
    assert "night" not in rows[("water", None)].by_column
    assert "night" in rows[("film", None)].by_column


def test_production_hours_and_arret_hours_are_in_hours_not_minutes():
    rows = _rows(daily=[DailyFact(column="morning", production_minutes=394.2, downtime_minutes=85.8)])
    assert rows[("production_hours", None)].by_column["morning"] == pytest.approx(6.57)
    assert rows[("downtime_hours", None)].by_column["morning"] == pytest.approx(1.43)


def test_hourly_output_is_kilos_of_total_fab_over_hours_worked():
    rows = _rows(daily=[DailyFact(column="morning", production_minutes=420, semolina=(("s", "S", 12.0),), regrind_t=1.0)])
    # 13 t over 7 h is 1 857 kg/h -- the Excel's own figure for its first shift.
    assert rows[("hourly_output", None)].by_column["morning"] == pytest.approx(13000 / 7)


def test_the_days_hourly_output_is_the_days_kilos_over_the_days_hours_not_a_sum_of_rates():
    rows = _rows(
        daily=[
            DailyFact(column="morning", production_minutes=60, semolina=(("s", "S", 1.0),)),
            DailyFact(column="night", production_minutes=180, semolina=(("s", "S", 1.0),)),
        ]
    )
    row = rows[("hourly_output", None)]
    assert row.by_column == {"morning": pytest.approx(1000), "night": pytest.approx(1000 / 3)}
    assert row.total == pytest.approx(2000 / 4)


def test_a_column_with_no_hours_worked_has_no_hourly_output():
    rows = _rows(daily=[DailyFact(column="morning", production_minutes=0, semolina=(("s", "S", 1.0),))])
    assert rows[("hourly_output", None)].by_column == {}
    assert rows[("hourly_output", None)].total is None


def test_waste_is_a_row_per_kind_and_the_total_adds_them():
    rows = _rows(
        daily=[
            DailyFact(column="morning", waste_kg=(("raw_material", 2.0), ("kneading", 1.0))),
            DailyFact(column="night", waste_kg=(("raw_material", 5.0),)),
        ]
    )
    assert rows[("waste", "raw_material")].by_column == {"morning": 2.0, "night": 5.0}
    assert rows[("waste", "kneading")].by_column == {"morning": 1.0}
    assert rows[("total_waste", None)].by_column == {"morning": 3.0, "night": 5.0}


def test_finished_product_is_a_row_per_product_largest_first_and_total_cdt_adds_them():
    rows = _rows(
        packing=[
            PackingFact(column="morning", product_id="small", product_name="Douman 200 g", finished_t=1.0),
            PackingFact(column="morning", product_id="big", product_name="Douman 500 g", finished_t=13.0),
        ]
    )
    order = [row.name for row in rows.values() if row.key == "finished"]
    assert order == ["Douman 500 g", "Douman 200 g"]
    assert rows[("total_finished", None)].by_column == {"morning": 14.0}


def test_the_yield_is_conditionned_tonnes_over_tonnes_put_into_fabrication():
    rows = _rows(
        daily=[DailyFact(column="morning", semolina=(("s", "S", 12.0),), regrind_t=1.0)],
        packing=[PackingFact(column="morning", product_id="p", product_name="P", finished_t=13.0 * 0.9)],
    )
    assert rows[("yield", None)].total == pytest.approx(90.0)


def test_there_is_no_yield_without_both_sides():
    only_daily = _rows(daily=[DailyFact(column="morning", semolina=(("s", "S", 12.0),))])
    only_packing = _rows(packing=[PackingFact(column="morning", product_id="p", finished_t=5.0)])
    assert only_daily[("yield", None)].total is None
    assert only_packing[("yield", None)].total is None


def test_a_shifts_yield_is_left_out_by_default_because_packing_lags_production():
    rows = _rows(
        daily=[DailyFact(column="morning", semolina=(("s", "S", 12.0),)), DailyFact(column="night", semolina=(("s", "S", 6.0),))],
        packing=[PackingFact(column="night", product_id="p", finished_t=15.0)],
    )
    assert rows[("yield", None)].by_column == {}
    assert rows[("yield", None)].total == pytest.approx(15 / 18 * 100)


def test_a_products_yield_is_read_per_column_on_the_recap():
    rows = _rows(
        daily=[
            DailyFact(column="douman", semolina=(("s", "S", 10.0),), regrind_t=0.0),
            DailyFact(column="prima", semolina=(("s", "S", 20.0),)),
        ],
        packing=[
            PackingFact(column="douman", product_id="d", finished_t=9.0),
            PackingFact(column="prima", product_id="p", finished_t=15.0),
        ],
        yield_by_column=True,
    )
    yield_row = rows[("yield", None)]
    assert yield_row.by_column == {"douman": pytest.approx(90.0), "prima": pytest.approx(75.0)}
    # The whole line's yield is its tonnes over its tonnes, not the average of the two.
    assert yield_row.total == pytest.approx(24 / 30 * 100)


def test_a_column_that_conditioned_something_but_fabricated_nothing_has_no_yield():
    rows = _rows(packing=[PackingFact(column="douman", product_id="d", finished_t=9.0)], yield_by_column=True)
    assert rows[("yield", None)].by_column == {}


def test_packing_waste_keeps_each_item_apart_because_each_is_in_its_own_unit():
    rows = build_rows(
        [],
        [
            PackingFact(
                column="morning",
                waste=(("packaging", "film", "Film", 8.0, "kg"), ("packaging", "carton", "Carton", 3.0, "ea")),
            )
        ],
    )
    waste = {row.name: row for row in rows if row.key == "packing_waste"}
    assert (waste["Film"].unit, waste["Film"].total) == ("kg", 8.0)
    assert (waste["Carton"].unit, waste["Carton"].total) == ("ea", 3.0)
    # Only kilos add up to kilos: the carton is shown but not added to the packaging total.
    total = next(row for row in rows if row.key == "total_packing_waste")
    assert (total.section, total.unit, total.total) == ("packing", "kg", 8.0)


def test_product_lost_while_packing_is_pasta_and_counts_in_the_total_waste_but_film_does_not():
    rows = build_rows(
        [DailyFact(column="morning", waste_kg=(("press", 40.0),))],
        [
            PackingFact(
                column="afternoon",
                waste=(("product", "coq", "Coquiette", 6.0, "kg"), ("packaging", "film", "Film", 2.5, "kg")),
            )
        ],
    )
    product = next(row for row in rows if row.key == "packed_product_waste")
    assert (product.section, product.ref, product.unit, product.by_column) == ("waste", "coq", "kg", {"afternoon": 6.0})
    assert not [row for row in rows if row.key == "packing_waste" and row.ref == "product"]
    total_waste = next(row for row in rows if row.key == "total_waste")
    assert total_waste.by_column == {"morning": 40.0, "afternoon": 6.0}
    film = next(row for row in rows if row.key == "packing_waste")
    assert (film.section, film.total) == ("packing", 2.5)
    assert next(row for row in rows if row.key == "total_packing_waste").total == 2.5
    # The product lost sits with the other déchets, before their total.
    keys = [row.key for row in rows]
    assert keys.index("waste") < keys.index("packed_product_waste") < keys.index("total_waste")


def test_a_packing_report_that_lost_nothing_reads_zero_packaging_waste_not_no_report():
    rows = build_rows([], [PackingFact(column="night")])
    total = next(row for row in rows if row.key == "total_packing_waste")
    assert total.by_column == {"night": 0.0}


def test_packaging_rows_carry_the_unit_the_caller_restated_them_into():
    rows = _rows(packing=[PackingFact(column="morning", film=10.0)], packaging_units={"film": "kg", "carton": "ea"})
    assert rows[("film", None)].unit == "kg"
    assert rows[("carton", None)].unit == rows[("waste_carton", None)].unit == "ea"


def test_sections_come_out_in_the_order_the_excel_prints_them():
    rows = build_rows(
        [DailyFact(column="m", semolina=(("s", "S", 1.0),), waste_kg=(("press", 1.0),))],
        [PackingFact(column="m", product_id="p", finished_t=1.0)],
    )
    order = []
    for row in rows:
        if row.section not in order:
            order.append(row.section)
    assert order == ["material", "production", "waste", "packing", "energy"]
