import datetime

from modules.scan.domain.common import map_header, map_silo, map_stops
from modules.scan.domain.draft import Draft, header_path, path
from modules.scan.domain.example_pages import context, make_page
from modules.scan.domain.ocr_result import ReadCell


def _reasons(draft, at):
    return [flag["reason"] for flag in draft.flags.get(at, [])]


def test_stops_are_split_inferred_and_timed():
    draft = Draft(context())
    page = make_page("P", "fabrication", {}, {"stops": [
        {"panne": "Démarrage de la production à 09h27mn"},
        {"panne": "Alarme silo à reprises 10h43-10h53, 12h56-12h58"},
        {"panne": "coupure sur l'EDM", "start": "12h18", "end": "12h37", "action": "Production sur GE"},
    ]})
    map_stops(page, draft, "stops")
    stops = draft.sections["stops"]["stops"]
    assert [(s["started_at"], s["ended_at"]) for s in stops] == [
        ("2026-09-07T07:00", "2026-09-07T09:27"),
        ("2026-09-07T10:43", "2026-09-07T10:53"),
        ("2026-09-07T12:56", "2026-09-07T12:58"),
        ("2026-09-07T12:18", "2026-09-07T12:37"),
    ]
    assert _reasons(draft, path("stops", "stops", stops[0]["_scan_ref"], "started_at")) == ["inferred_stop"]
    assert _reasons(draft, path("stops", "stops", stops[1]["_scan_ref"], "started_at")) == ["split_stop"]
    assert (stops[3]["note"], stops[3]["corrective_action"]) == ("coupure sur l'EDM", "Production sur GE")


def test_night_shift_times_after_midnight_are_next_day():
    draft = Draft(context(shift_start=datetime.time(23, 0), shift_end=datetime.time(7, 0)))
    page = make_page("P", "fabrication", {}, {"stops": [{"panne": "panne presse", "start": "23h40", "end": "01h10"}]})
    map_stops(page, draft, "stops")
    stop = draft.sections["stops"]["stops"][0]
    assert (stop["started_at"], stop["ended_at"]) == ("2026-09-07T23:40", "2026-09-08T01:10")


def test_silo_rows_carry_side_and_phase():
    draft = Draft(context())
    page = make_page("P", "conditionnement", {}, {
        "silo_start": [{"format": "Vermicelles", "lot": "D6249SNL", "level": "20 %", "line_state": "En Arrêt"}],
        "silo_end": [{"level": "29 %", "line_state": "En Marche"}],
    })
    map_silo(page, draft, "packing")
    states = draft.sections["silo"]["states"]
    assert [(s["side"], s["phase"], s["level_percent"], s["line_state"]) for s in states] == [
        ("packing", "start", 20.0, "stopped"), ("packing", "end", 29.0, "running"),
    ]


def test_header_names_team_and_mismatch():
    draft = Draft(context(team="Equipe A"))
    page = make_page("P", "fabrication", {"team_hours": "D 07 H à 14H00", "conducteur": "Conducteur Un"}, {})
    map_header(page, draft, ("conducteur", "agent_fabrication"))
    assert draft.header == {"team": "Equipe A", "conducteur": "Conducteur Un"}
    assert _reasons(draft, header_path("team")) == ["team_mismatch"]
    assert draft.coded[header_path("conducteur")] == {"kind": "person", "read_text": "Conducteur Un", "value": "Conducteur Un"}


def test_a_new_shift_takes_the_team_named_by_its_letter():
    draft = Draft(context(team=None))
    map_header(make_page("P", "fabrication", {"team_hours": "D 07 H"}, {}), draft, ())
    assert draft.header["team"] == "Equipe D" and draft.team_letter_read == "D"


def test_lots_are_completed_and_checked_against_the_shift():
    draft = Draft(context())
    run = draft.add_row("runs", "runs", "r", {})
    waste = draft.add_row("waste_production", "waste_lines", "w", {})
    draft.lot(path("runs", "runs", "r", "lot_number"), ReadCell("D6249SNL", 0.9, None, "P"), run, "lot_number", check=True)
    draft.lot(path("waste_production", "waste_lines", "w", "lot_number"), ReadCell("D6249", 0.9, None, "P"), waste, "lot_number")
    draft.finish()
    assert waste["lot_number"] == "D6249SNL"
    assert _reasons(draft, path("waste_production", "waste_lines", "w", "lot_number")) == ["short_lot"]
    assert {"reason": "lot_date", "detail": "2026-09-06"} in draft.flags[path("runs", "runs", "r", "lot_number")]


def test_low_confidence_and_unreadable_cells_are_flagged():
    draft = Draft(context())
    assert draft.decimal("a/b/c/d", ReadCell("abc", 0.2, None, "P")) is None
    assert _reasons(draft, "a/b/c/d") == ["low_confidence", "unreadable"]
    assert draft.sources["a/b/c/d"] == [{"page_id": "P", "box": None, "text": "abc", "confidence": 0.2}]
