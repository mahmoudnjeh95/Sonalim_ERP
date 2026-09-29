from modules.scan.domain.conditionnement import map_conditionnement
from modules.scan.domain.draft import Draft, path
from modules.scan.domain.example_pages import conditionnement_page, context, fabrication_page, make_page
from modules.scan.domain.fabrication import map_fabrication


def _reasons(draft, at):
    return [flag["reason"] for flag in draft.flags.get(at, [])]


def _fabrication():
    draft = Draft(context())
    map_fabrication(fabrication_page(), draft)
    return draft


def _conditionnement(page=None):
    draft = Draft(context())
    map_conditionnement(page or conditionnement_page(), draft)
    return draft


def test_fabrication_run_and_versements():
    draft = _fabrication()
    runs = draft.sections["runs"]
    [run] = runs["runs"]
    assert (run["of_id"], run["lot_number"], run["start_time"], run["water_percentage"], run["humidity_percentage"]) == (
        "OF1", "D6249SNL", "07:00", 28.9, 9.83,
    )
    assert [(v["product_id"], v["quantity"]) for v in runs["versements"]] == [("MP-SSSE", 3.25), (None, 3.3)]
    assert _reasons(draft, path("runs", "versements", runs["versements"][1]["_scan_ref"], "product_id")) == ["unresolved"]
    assert path("runs", "runs", run["_scan_ref"], "of_id") not in draft.flags  # "Vermicelle" is the OF's product


def test_fabrication_run_minutes_from_its_hours():
    draft = Draft(context())
    map_fabrication(make_page("P", "fabrication", {}, {"production": [{"lot": "D6250SNL", "start": "07h00", "end": "14h00"}]}), draft)
    assert draft.sections["runs"]["runs"][0]["production_minutes"] == 420


def test_fabrication_waste_goes_to_the_right_side():
    draft = _fabrication()
    petrin = draft.sections["waste_production"]["waste_lines"]
    assert [(w["category"], w["quantity"], w["occurred_at"]) for w in petrin] == [
        ("press", 1.47, "2026-09-07T14:00"), (None, 5.0, "2026-09-07T14:00"),
    ]
    [finished] = draft.sections["waste_packing"]["waste_lines"]
    assert (finished["category"], finished["quantity"]) == ("product", 75.25)
    assert draft.fabrication_losses == [finished]


def test_fabrication_header_stops_and_silo():
    draft = _fabrication()
    assert draft.header == {"team": "Equipe D", "conducteur": "Conducteur Un", "agent_fabrication": "Agent Deux"}
    assert len(draft.sections["stops"]["stops"]) == 4
    assert [(s["side"], s["phase"]) for s in draft.sections["silo"]["states"]] == [("production", "start"), ("production", "end")]
    assert "staffing" not in draft.sections


def test_fabrication_staffing_and_mold_washes():
    draft = Draft(context())
    page = make_page("P", "fabrication", {}, {
        "staffing": [{"control_room": "1", "petrin": "2", "semoule": "1", "broyage": ""}],
        "mold_washes": [{"mold": "M12", "time": "10h", "state": "propre"}],
    })
    map_fabrication(page, draft)
    assert draft.sections["staffing"]["staffing"] == {"control_room": 1, "petrin": 2, "semoule": 1, "broyage": None}
    [wash] = draft.sections["waste_production"]["mold_washes"]
    assert (wash["mold_id"], wash["washed_at"], wash["state"]) == (None, "2026-09-07T10:00", "propre")


def test_conditionnement_packing_row():
    draft = _conditionnement()
    [row] = draft.sections["packing"]["rows"]
    assert (row["product_id"], row["of_id"], row["lot_number"], row["film_product_id"]) == ("P-VERM", "OF1", "D6249SNL", "FILM-ACT")
    assert (row["carton_quantity"], row["tape_quantity"], row["scotch_quantity"], row["ruban_quantity"]) == (1.0, 1.0, None, None)
    at = lambda field: path("packing", "rows", row["_scan_ref"], field)  # noqa: E731
    assert _reasons(draft, at("carton_quantity")) == ["lookalike"]
    assert _reasons(draft, at("scotch_quantity")) == ["unreadable"]
    assert _reasons(draft, at("film_product_id")) == ["partial_match"]
    assert at("product_id") not in draft.flags


def test_packing_format_that_is_not_the_products_weight():
    page = make_page("P", "conditionnement", {}, {"packing": [{"format": "Vermicelles", "lot": "D6250SNL", "pack_type": "(250g)"}]})
    draft = _conditionnement(page)
    row = draft.sections["packing"]["rows"][0]
    assert draft.flags[path("packing", "rows", row["_scan_ref"], "product_id")] == [{"reason": "format_mismatch", "detail": "250 g"}]


def test_conditionnement_waste_skips_nothing_written_as_00():
    lines = _conditionnement().sections["waste_packing"]["waste_lines"]
    assert [(line["category"], line["quantity"]) for line in lines] == [("product", 2.46), (None, 0.35), (None, 0.23), (None, 75.28)]
    assert lines[0]["product_id"] == "P-VERM" and lines[1]["product_id"] is None


def test_packet_checks():
    page = make_page("P", "conditionnement", {}, {"packet_checks": [
        {"time": "08h00", "film": "Bon", "weight": "502", "long_weld": "B", "vert_weld": "NB", "date_print": "OK", "observation": "RAS"},
    ]})
    [check] = _conditionnement(page).sections["packet_checks"]["checks"]
    assert {k: v for k, v in check.items() if k != "_scan_ref"} == {
        "checked_at": "2026-09-07T08:00", "film_state": "good", "packet_weight_grams": 502.0,
        "long_weld": "good", "vertical_weld": "not_good", "date_print": "good", "note": "RAS",
    }
