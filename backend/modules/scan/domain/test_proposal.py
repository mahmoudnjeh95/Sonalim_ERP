import datetime
import json

from modules.scan.domain.attribution import Selection
from modules.scan.domain.example_pages import bobines_page, conditionnement_page, context, fabrication_page, make_page
from modules.scan.domain.proposal import build_proposal
from modules.scan.domain.review import (
    aliases_to_learn, count_rows, final_values, fingerprint, outcomes, stale_sections, strip_private,
)

SELECTION = Selection(report_date=datetime.date(2026, 9, 7), shift_start=datetime.time(7, 0), line_label="PC")


def _build(pages, include=()):
    return build_proposal(pages, context(), SELECTION, include_pages=include)


def test_the_example_upload():
    proposal = _build([fabrication_page(), conditionnement_page(), bobines_page()])
    pages = proposal["pages"]
    assert pages["FAB"]["included"] and pages["COND"]["included"]
    assert (pages["BOB"]["verdict"], pages["BOB"]["importable"], pages["BOB"]["included"]) == ("other_shift", False, False)
    assert set(proposal["sections"]) == {"runs", "waste_production", "stops", "silo", "packing", "waste_packing"}
    assert len(proposal["sections"]["silo"]["states"]) == 4
    [aside] = proposal["set_aside"]["waste_packing"]
    assert aside["reason"] == "same_loss" and aside["row"]["quantity"] == 75.25
    assert [line["quantity"] for line in proposal["sections"]["waste_packing"]["waste_lines"]] == [2.46, 0.35, 0.23, 75.28]
    assert proposal["header"] == {
        "team": "Equipe D", "conducteur": "Conducteur Un", "agent_fabrication": "Agent Deux",
        "machiniste": "Machiniste Trois", "aide_machiniste": "Aide Quatre",
    }
    json.dumps(proposal)  # everything is JSON-safe


def test_an_other_shift_page_is_used_only_when_included():
    page = make_page("LATE", "fabrication", {"date": "07/09/26", "team_hours": "A 15H", "line_pc": "x"}, {"stops": [{"panne": "x", "start": "16h00"}]})
    assert "stops" not in _build([page])["sections"]
    assert "stops" in _build([page], include={"LATE"})["sections"]


def test_a_retake_does_not_duplicate_silo_rows():
    proposal = _build([fabrication_page("A"), fabrication_page("B")])
    assert len(proposal["sections"]["silo"]["states"]) == 2
    assert len(proposal["sections"]["stops"]["stops"]) == 4


def test_without_the_conditionnement_sheet_the_finished_loss_stays():
    proposal = _build([fabrication_page()])
    assert proposal["set_aside"] == {}
    assert proposal["sections"]["waste_packing"]["waste_lines"][0]["quantity"] == 75.25


def test_final_values_and_strip_private():
    sections = {"runs": {"runs": [{"_scan_ref": "R1", "_key": "k", "of_id": "OF1", "lot_number": "L"}]}, "staffing": {"staffing": {"petrin": 2}}}
    assert final_values(sections, {"team": "Equipe D"}) == {
        "header/-/-/team": "Equipe D", "runs/runs/R1/of_id": "OF1", "runs/runs/R1/lot_number": "L", "staffing/staffing/-/petrin": 2,
    }
    assert strip_private(sections["runs"]) == {"runs": [{"of_id": "OF1", "lot_number": "L"}]}


def test_fingerprint_ignores_key_order_and_count_rows():
    assert fingerprint({"runs": [{"a": 1, "b": 2}], "energy": None}) == fingerprint({"energy": None, "runs": [{"b": 2, "a": 1}]})
    assert count_rows({"runs": [{}, {}], "versements": [], "staffing": {"petrin": 1}, "energy": None}) == 3


def test_stale_sections():
    current = {"runs": {"fingerprint": "f1", "rows": 2}, "stops": {"fingerprint": "f2", "rows": 0}}
    assert stale_sections(["runs"], current, {"runs": "f1"}) == []
    assert stale_sections(["runs"], current, {"runs": "old"}) == ["runs"]
    assert stale_sections(["runs", "stops"], current, {}) == ["runs"]  # nothing shown, rows appeared since
    assert stale_sections(["runs"], None, {}) == []


def test_outcomes_compare_proposed_and_final():
    proposal = {
        "header": {}, "sections": {"runs": {"runs": [{"_scan_ref": "R1", "lot_number": "D6249SNL", "water_percentage": 28.9}]}},
        "sources": {
            "runs/runs/R1/lot_number": [{"page_id": "P", "box": None, "text": "D6249SNL", "confidence": 0.8}],
            "runs/runs/R1/water_percentage": [{"page_id": "P", "box": None, "text": "28,9", "confidence": 0.7}],
        },
        "flags": {"runs/runs/R1/lot_number": [{"reason": "lot_date", "detail": "2026-09-06"}]},
    }
    rows = outcomes(proposal, {"runs/runs/R1/lot_number": "D6250SNL", "runs/runs/R1/water_percentage": "28.9"})
    assert rows == [
        {"field_path": "runs/runs/R1/lot_number", "page_id": "P", "read_text": "D6249SNL", "confidence": 0.8,
         "proposed_value": "D6249SNL", "final_value": "D6250SNL", "flag": "lot_date", "changed": True},
        {"field_path": "runs/runs/R1/water_percentage", "page_id": "P", "read_text": "28,9", "confidence": 0.7,
         "proposed_value": "28.9", "final_value": "28.9", "flag": None, "changed": False},
    ]


def test_aliases_to_learn():
    coded = {
        "runs/versements/V1/product_id": {"kind": "raw_material", "read_text": "B05I", "value": None},
        "header/-/-/conducteur": {"kind": "person", "read_text": "Raclne", "value": "Raclne"},
        "runs/versements/V0/product_id": {"kind": "raw_material", "read_text": "BSK1", "value": "MP-1"},
    }
    finals = {"runs/versements/V1/product_id": "MP-2", "header/-/-/conducteur": "Racine", "runs/versements/V0/product_id": "MP-1"}
    assert aliases_to_learn(coded, finals) == [("raw_material", "B05I", "MP-2"), ("person", "Raclne", "Racine")]
    assert aliases_to_learn(coded, {"runs/versements/V1/product_id": None}) == []
