"""The month workbook, built from facts laid out by hand -- no database needed.

What is checked is the shape a manager reads: the sheets come in the plant's order
(recap, recap by lot, the PC line's days before the PL line's, then consumption,
energy and the analyses), every day of the month up to today has its sheet, and the
figures on the recap are the ones the facts add up to.
"""
from __future__ import annotations

import datetime
import io

import pytest
from openpyxl import load_workbook

from modules.production.api.day_sheet_service import (
    NO_LOT,
    NO_PRODUCT,
    NO_SHIFT,
    LoadedSheet,
    assemble,
    lot_columns,
    product_columns,
    shift_columns,
)
from modules.production.api.month_recap_export import (
    Agg,
    LineMonth,
    MonthRecapData,
    aggregate,
    build_month_recap_workbook,
    line_tag,
    line_total,
)
from modules.production.domain.dashboard import ShiftWindow
from modules.production.domain.day_sheet import DailyFact, PackingFact

MONTH = datetime.date(2026, 9, 1)
TODAY = datetime.date(2026, 9, 5)
WINDOWS = {
    "morning": ShiftWindow(shift="morning", start=datetime.time(7), end=datetime.time(14)),
    "night": ShiftWindow(shift="night", start=datetime.time(22), end=datetime.time(7)),
}


def _report(i, kind, day, *, shift="morning", team="Équipe A", lot="B7101SNL", product="Coquillette 500 g", status="validated"):
    return {
        "id": i, "type": kind, "shift": shift, "team": team, "status": status, "of_id": "of-1",
        "product_id": "coq", "product_name": product, "date": MONTH.replace(day=day), "lot": lot,
    }


def _loaded() -> LoadedSheet:
    reports = [
        _report("d1", "daily", 1),
        _report("p1", "conditionnement", 1),
        _report("d2", "daily", 2, shift="night", team="Équipe C", lot="B7102SNL"),
        _report("p2", "conditionnement", 2, shift="night", team="Équipe C", lot="B7102SNL"),
        _report("d3", "daily", 3, status="submitted"),
    ]
    daily = {
        "d1": DailyFact(
            column="", water_l=4000, production_minutes=420, downtime_minutes=60, regrind_t=0.5, fuel_l=100, gasoil_l=20,
            electricity_kwh=2000, generator_hours=1, semolina=(("salem", "Semoule Salem", 10.0),), waste_kg=(("press", 40.0),),
        ),
        "d2": DailyFact(
            column="", water_l=2000, production_minutes=300, downtime_minutes=30, regrind_t=0.0, electricity_kwh=1000,
            semolina=(("salem", "Semoule Salem", 5.0), ("fine", "Semoule fine", 1.0)),
        ),
    }
    packing = {
        "p1": PackingFact(column="", product_id="coq", product_name="Coquillette 500 g", finished_t=9.0, packets=18000, film=100, carton=900),
        "p2": PackingFact(column="", product_id="coq", product_name="Coquillette 500 g", finished_t=5.0, packets=10000, film=50, carton=500,
                          waste=(("packaging", "film", "Film", 2.0, "kg"), ("product", "coq", "Coquillette 500 g", 3.0, "kg"))),
    }
    return LoadedSheet(
        reports=reports,
        daily_facts=daily,
        packing_facts=packing,
        packaging_units={"film": "kg", "carton": "ea"},
        products={"coq": {"name": "Coquillette 500 g"}},
        stops={"d1": [("format_change", None, None, 60.0)], "d2": [("die_jam", "corrective", "mechanical", 30.0)]},
        ofs={"of-1": {"id": "of-1", "reference": "OF-1", "product_name": "Coquillette 500 g"}},
    )


def _line_month(name: str, code: str, loaded: LoadedSheet | None = None) -> LineMonth:
    loaded = loaded or LoadedSheet(reports=[])
    by_product = assemble(loaded, column_of=lambda r: r["product_id"] or NO_PRODUCT, yield_by_column=True)
    by_product["columns"] = product_columns(by_product["columns"], loaded.products)
    by_lot = assemble(loaded, column_of=lambda r: r["lot"] or NO_LOT, yield_by_column=True)
    by_lot["columns"] = lot_columns(by_lot["columns"])
    days = []
    for n in range((TODAY - MONTH).days + 1):
        day = MONTH + datetime.timedelta(days=n)
        sheet = assemble(loaded, column_of=lambda r: r["shift"] or NO_SHIFT, include=lambda r, d=day: r["date"] == d)
        columns = shift_columns(sheet["columns"], WINDOWS)
        days.append({
            "date": day, "columns": columns, "rows": sheet["rows"], "ofs": sheet["ofs"],
            "validated": sum(c["reports"][k]["validated"] for c in columns for k in ("daily", "conditionnement")),
            "pending": sum(c["reports"][k]["pending"] for c in columns for k in ("daily", "conditionnement")),
        })
    tag = line_tag(name, code)
    return LineMonth(line={"id": code, "code": code, "name": name}, tag=tag, sheet_prefix=tag, by_product=by_product, by_lot=by_lot, days=days, loaded=loaded)


@pytest.fixture
def workbook():
    data = MonthRecapData(
        month=MONTH, generated_on=TODAY,
        lines=[_line_month("Line_2_PC", "L2", _loaded()), _line_month("Line_1_PL", "L1")],
        waste_labels={"press": "Presse", "packaging": "Emballage"},
        motif_labels={"format_change": "Changement de format", "die_jam": "Bourrage filière"},
    )
    return load_workbook(io.BytesIO(build_month_recap_workbook(data)))


def test_the_line_family_is_read_off_the_name_or_code():
    assert line_tag("Line_2_PC", "L2") == "PC"
    assert line_tag("Ligne 1 PL", "LINE-PL") == "PL"
    assert line_tag("Broyeur", "BRY") == "BRY"
    # "PLastique" is not the PL family.
    assert line_tag("Plastique", "PLA") == "PLA"


def test_the_sheets_come_in_the_plants_order_with_a_day_sheet_per_line_and_per_day(workbook):
    names = workbook.sheetnames
    pc_days = [f"PC {d:02d}" for d in range(1, 6)]
    pl_days = [f"PL {d:02d}" for d in range(1, 6)]
    assert names == [
        "Récap", "Récap par lot", *pc_days, *pl_days,
        "Conso production", "Conso conditionnement", "Énergie", "Arrêts", "Déchets", "Équipes", "Tendance",
    ]


def test_the_recap_sheet_adds_the_month_up_per_line_and_for_the_plant(workbook):
    ws = workbook["Récap"]
    # The overview block ends where the first line's own grid starts.
    end = next(r for r in range(1, 80) if ws.cell(row=r, column=1).value == "PC · Line_2_PC — récap par produit")
    cells = {ws.cell(row=r, column=1).value: [ws.cell(row=r, column=c).value for c in range(3, 6)] for r in range(1, end)}
    # Total MP is the semoule poured on validated runs only (10 + 5 + 1); the submitted run is not added.
    assert cells["Total MP (semoule)"] == [pytest.approx(16.0), "—", pytest.approx(16.0)]
    assert cells["Total fabrication"] == [pytest.approx(16.5), "—", pytest.approx(16.5)]
    assert cells["Total conditionné"] == [pytest.approx(14.0), "—", pytest.approx(14.0)]
    assert cells["Rendement (conditionné ÷ fabrication)"][0] == pytest.approx(14 / 16.5 * 100)
    assert cells["Rapports non validés (non comptés)"] == [1, 0, 1]
    assert cells["Lots"] == [2, 0, 2]
    # Then the line's own grid, a column per product.
    labels = [ws.cell(row=r, column=1).value for r in range(1, 80)]
    assert "PC · Line_2_PC — récap par produit" in labels
    assert "PL · Line_1_PL — récap par produit" in labels
    grid_header = next(r for r in range(1, 80) if ws.cell(row=r, column=1).value == "Line_2_PC")
    assert ws.cell(row=grid_header, column=3).value == "Coquillette 500 g"


def test_the_lot_sheet_has_one_row_per_lot_with_what_went_in_and_what_came_out(workbook):
    ws = workbook["Récap par lot"]
    rows = {ws.cell(row=r, column=1).value: [ws.cell(row=r, column=c).value for c in range(1, 18)] for r in range(1, 30)}
    first = rows["B7101SNL"]
    assert first[1] == "Coquillette 500 g"
    assert first[2] == datetime.datetime(2026, 9, 1) and first[3] == datetime.datetime(2026, 9, 1)
    assert first[4] == 2  # a run and a packing
    assert first[5] == pytest.approx(10.0) and first[6] == pytest.approx(0.5) and first[7] == pytest.approx(10.5)
    assert first[11] == pytest.approx(9.0) and first[12] == pytest.approx(9 / 10.5 * 100)
    second = rows["B7102SNL"]
    assert second[5] == pytest.approx(6.0) and second[11] == pytest.approx(5.0)


def test_a_day_sheet_prints_the_days_reports_a_column_per_shift_and_says_when_there_are_none(workbook):
    day_two = workbook["PC 02"]
    assert day_two["A1"].value == "Line_2_PC — fiche du mercredi 2 septembre 2026"
    header = next(r for r in range(1, 12) if day_two.cell(row=r, column=1).value == "Line_2_PC")
    assert [day_two.cell(row=header, column=c).value for c in range(3, 6)] == ["Morning", "Night", "Total"]
    labels = {day_two.cell(row=r, column=1).value: r for r in range(header, 60)}
    total_mp = labels["Total MP"]
    assert day_two.cell(row=total_mp, column=3).value == "—"
    assert day_two.cell(row=total_mp, column=4).value == pytest.approx(6.0)
    assert day_two.cell(row=total_mp, column=5).value == pytest.approx(6.0)
    assert day_two.cell(row=labels["Équipe"], column=4).value == "Équipe C"
    assert day_two.cell(row=labels["Lot"], column=4).value == "B7102SNL"

    day_three = workbook["PC 03"]
    assert "1 non validé(s)" in day_three["A2"].value
    empty = workbook["PL 04"]
    assert "aucun rapport" in empty["A2"].value


def test_the_analysis_sheets_add_the_same_facts_up_by_day_lot_motif_and_team(workbook):
    energy = workbook["Énergie"]
    first_day = next(r for r in range(1, 30) if energy.cell(row=r, column=1).value == datetime.datetime(2026, 9, 1))
    assert energy.cell(row=first_day, column=3).value == 2000
    assert energy.cell(row=first_day, column=9).value == pytest.approx(2000 / 10.5)

    stops = workbook["Arrêts"]
    motifs = {stops.cell(row=r, column=2).value: stops.cell(row=r, column=4).value for r in range(1, 30)}
    assert motifs["Changement de format"] == 60 and motifs["Bourrage filière"] == 30

    teams = workbook["Équipes"]
    by_team = {teams.cell(row=r, column=1).value: teams.cell(row=r, column=4).value for r in range(1, 30)}
    assert by_team["Équipe A"] == pytest.approx(10.5) and by_team["Équipe C"] == pytest.approx(6.0)

    waste = workbook["Déchets"]
    kinds = {waste.cell(row=r, column=2).value: waste.cell(row=r, column=3).value for r in range(1, 30)}
    assert kinds["Presse"] == 40
    # Pasta lost while packing counts in the déchets' total; film is not pasta, so it is
    # listed apart and left out of it.
    assert kinds["Produit fini (conditionnement) · Coquillette 500 g"] == 3
    assert kinds["Total déchets"] == 43
    packaging = {waste.cell(row=r, column=1).value: waste.cell(row=r, column=2).value for r in range(1, 30)}
    assert packaging["Déchet emballage · Film"] == 2 and packaging["Total déchets emballage"] == 2

    trend = workbook["Tendance"]
    assert trend._charts, "the trend sheet carries its charts"


def test_aggregates_read_ratios_as_none_when_there_is_nothing_to_divide():
    loaded = _loaded()
    by_lot = aggregate(loaded, lambda r: r["lot"])
    assert by_lot["B7101SNL"].kg_per_hour == pytest.approx(10.5 * 1000 / 7)
    assert by_lot["B7101SNL"].downtime_pct == pytest.approx(60 / 480 * 100)
    total = line_total(loaded)
    assert total.fab_t == pytest.approx(16.5) and total.finished_t == pytest.approx(14.0)
    assert Agg().kg_per_hour is None and Agg().yield_pct is None and Agg().per_tonne(10) is None


def test_packing_ratios_leave_out_waste_cartons_and_a_mould_change_day_gets_a_row_per_product():
    reports = [
        _report("p1", "conditionnement", 1, product="Coquillette 500 g"),
        _report("p2", "conditionnement", 1, shift="night", lot="B7102SNL", product="Coquillette 200 g"),
    ]
    packing = {
        # 1 000 cartons of 20 x 500 g = 10 T; the 10 waste cartons hold nothing.
        "p1": PackingFact(column="", product_name="Coquillette 500 g", finished_t=10.0, packets=20000, carton=1010, waste_carton=10),
        # The mould is changed the same day: 500 cartons of 40 x 200 g = 4 T.
        "p2": PackingFact(column="", product_name="Coquillette 200 g", finished_t=4.0, packets=20000, carton=505, waste_carton=5),
    }
    loaded = LoadedSheet(reports=reports, packing_facts=packing, packaging_units={"carton": "ea"})
    data = MonthRecapData(month=MONTH, generated_on=TODAY, lines=[_line_month("Line_2_PC", "L2", loaded)])
    ws = load_workbook(io.BytesIO(build_month_recap_workbook(data)))["Conso conditionnement"]

    day_rows = {r[1]: (r[11], r[12]) for r in ws.iter_rows(values_only=True) if isinstance(r[1], str) and " · " in r[1]}
    assert day_rows == {
        "mardi · Coquillette 500 g": (pytest.approx(100), pytest.approx(20)),
        "mardi · Coquillette 200 g": (pytest.approx(125), pytest.approx(40)),
    }


# ---- untrusted text in cells -------------------------------------------------


@pytest.mark.parametrize("text", ["=1+1", "+34", "-7", "@SUM(A1)", '=HYPERLINK("http://x","clic")'])
def test_a_typed_name_cannot_become_a_formula(text):
    """Product names, motifs and notes are typed by users and land in this workbook.
    Excel reads a cell starting with = + - @ as a formula, so the export would run it on
    whoever opens the file."""
    from openpyxl import Workbook

    from modules.production.api.month_recap_export import _headers, _heading, _put, _title

    ws = Workbook().active

    _put(ws, 1, 1, text)
    _title(ws, 2, 3, text, subtitle=text)
    _heading(ws, 5, 3, text)
    _headers(ws, 6, [text, "Quantité"])

    for row, col in ((1, 1), (2, 1), (3, 1), (5, 1), (6, 1)):
        assert ws.cell(row=row, column=col).value == f"'{text}", f"cell {row},{col} is not neutralised"
    assert ws.cell(row=6, column=2).value == "Quantité"


def test_numbers_dates_and_ordinary_text_are_untouched():
    import datetime as dt

    from openpyxl import Workbook

    from modules.production.api.month_recap_export import _put

    ws = Workbook().active

    _put(ws, 1, 1, 12.5)
    _put(ws, 1, 2, dt.date(2026, 10, 5))
    _put(ws, 1, 3, "Rupture - manque de cartons")
    _put(ws, 1, 4, None)

    assert ws.cell(row=1, column=1).value == 12.5
    assert ws.cell(row=1, column=2).value == dt.date(2026, 10, 5)
    assert ws.cell(row=1, column=3).value == "Rupture - manque de cartons"
