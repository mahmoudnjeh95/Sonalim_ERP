import datetime

from modules.scan.domain.attribution import Selection, attribute, header_of_page, line_label_of
from modules.scan.domain.merge import merge_pages
from modules.scan.domain.ocr_result import ReadCell, page_read_from_json

SELECTION = Selection(report_date=datetime.date(2026, 9, 7), shift_start=datetime.time(7, 0), line_label="PC")


def _json(header=None, blocks=None, form_type="fabrication"):
    def cells(values):
        return {k: {"text": v[0], "confidence": v[1], "box": [0.1, 0.1, 0.2, 0.2]} for k, v in values.items()}
    return {
        "form_type": form_type, "rotation": 0, "accept_score": 0.5,
        "header": cells(header or {}),
        "blocks": [{"key": k, "found": True, "rows": [{"cells": cells(r)} for r in rows]} for k, rows in (blocks or {}).items()],
    }


def test_page_read_from_json_keeps_page_ids_and_found_blocks():
    page = page_read_from_json("P1", _json({"date": ("07/09/26", 0.9)}, {"stops": [{"panne": ("coupure", 0.6)}]}))
    assert page.head("date").page_id == "P1"
    assert page.block("stops").rows[0].cell("panne").text == "coupure"
    assert page.block("silo_start") is None
    assert page.head("missing").text == ""


def test_two_photos_of_the_same_block_merge_cell_by_cell():
    a = page_read_from_json("A", _json(blocks={"silo_start": [{"level": ("20 %", 0.4), "lot": ("D6249SNL", 0.9)}]}))
    b = page_read_from_json("B", _json(blocks={"silo_start": [{"level": ("0 %", 0.8), "lot": ("D6249SNL", 0.5)}]}))
    row = merge_pages([a, b]).block("silo_start").rows[0]
    assert (row.cell("level").text, row.cell("level").page_id, row.cell("level").conflict) == ("0 %", "B", "20 %")
    assert (row.cell("lot").page_id, row.cell("lot").conflict) == ("A", None)


def test_blocks_with_different_row_counts_keep_the_longer_one():
    a = page_read_from_json("A", _json(blocks={"stops": [{"panne": ("x", 0.9)}]}))
    b = page_read_from_json("B", _json(blocks={"stops": [{"panne": ("x", 0.9)}, {"panne": ("y", 0.9)}]}))
    block = merge_pages([a, b]).block("stops")
    assert len(block.rows) == 2 and block.rows_disagree


def test_line_label_from_the_line_name():
    assert line_label_of("LIGNE-PC", None) == "PC"
    assert line_label_of("Ligne pâtes longues PL") == "PL"
    assert line_label_of("Broyeur") is None


def test_same_shift():
    page = page_read_from_json("P", _json({"date": ("Le07/09/2026", 0.9), "team_hours": ("D 07 H à 14H00", 0.8), "line_pc": ("x", 0.9)}))
    result = attribute(header_of_page(page), SELECTION)
    assert result.verdict == "this_shift" and result.read == {"date": "2026-09-07", "team": "D", "hours_from": "07:00", "line": "PC"}


def test_other_shift_by_hours_and_line():
    page = page_read_from_json("P", _json({"date": ("07/09/26", 0.9), "team_hours": ("A 15H à 23H", 0.8), "line_pl": ("x", 0.9)}))
    result = attribute(header_of_page(page), SELECTION)
    assert result.verdict == "other_shift" and set(result.reasons) == {"hours", "line"}


def test_nothing_readable_is_unknown():
    page = page_read_from_json("P", _json({}))
    assert attribute(header_of_page(page), SELECTION).verdict == "unknown"


def test_the_bobines_sheet_is_judged_by_its_first_row():
    page = page_read_from_json("P", _json(blocks={"changes": [{"date": ("07/09/26", 0.9), "team": ("A", 0.9), "hours": ("14H23H", 0.9)}]}, form_type="bobines"))
    result = attribute(header_of_page(page), SELECTION)
    assert result.verdict == "other_shift" and result.reasons == ("hours",)
