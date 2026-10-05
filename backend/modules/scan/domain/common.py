"""What both fiches share: the header (team and names), the stops table and the silo."""
from __future__ import annotations

from functools import partial

from modules.scan.domain.draft import Draft, header_path, path, section_path
from modules.scan.domain.ocr_result import PageRead
from modules.scan.domain.text import Parsed, find_intervals, find_times, normalize, team_and_hours, team_letter


def map_header(page: PageRead, draft: Draft, person_fields: tuple[str, ...]) -> None:
    cell = page.head("team_hours")
    letter, _ = team_and_hours(cell.text)
    if letter:
        at = header_path("team")
        draft.see(at, cell)
        draft.team_letter_read = draft.team_letter_read or letter
        shift_letter = team_letter(draft.ctx.team)
        if shift_letter and shift_letter != letter:
            draft.flag(at, "team_mismatch", letter)
        if "team" not in draft.header:
            by_letter = next((t.value for t in draft.ctx.vocabulary.of("team") if t.attrs.get("letter") == letter), None)
            draft.header["team"] = draft.ctx.team or by_letter
    for field in person_fields:
        cell = page.head(field)
        written = cell.text.strip()
        if not written or field in draft.header:
            continue
        at = header_path(field)
        draft.see(at, cell)
        learned = draft.ctx.aliases.get(("person", normalize(written)))
        draft.coded[at] = {"kind": "person", "read_text": written, "value": learned or written}
        draft.header[field] = learned or written


def map_stops(page: PageRead, draft: Draft, block_key: str) -> None:
    """A paper stop line becomes one stop per interval written on it.

    Times are read from the start/end cells; when those hold no single time, from the
    whole line -- teams write "Alarme silo à reprises 10h43-10h53, 12h56-12h58" across
    the table. A line naming only a start ("Démarrage de la production à 09h27") is the
    time lost from the shift's start to it.
    """
    block = page.block(block_key)
    if block is None:
        return
    if block.rows_disagree:
        draft.flag(section_path("stops"), "rows_disagree")
    for index, row in enumerate(block.rows):
        if row.is_blank():
            continue
        panne, start, end, action = (row.cell(key) for key in ("panne", "start", "end", "action"))
        starts, ends = find_times(start.text), find_times(end.text)
        how = None
        if len(starts) == 1:
            spans = [(starts[0], ends[0] if len(ends) == 1 else None, start, end)]
        else:
            pairs = find_intervals(" ".join((start.text, end.text, panne.text)))
            lone = find_times(panne.text)
            if pairs:
                spans = [(a, b, panne, panne) for a, b in pairs]
                how = "split_stop" if len(pairs) > 1 else None
            elif len(lone) == 1 and "demarrage" in normalize(panne.text):
                spans = [(Parsed(draft.ctx.shift_start), lone[0], panne, panne)]
                how = "inferred_stop"
            elif len(lone) == 1:
                spans = [(lone[0], None, panne, panne)]
            else:
                spans = [(None, None, start, end)]
        for number, (begin, finish, begin_cell, finish_cell) in enumerate(spans):
            ref = f"{page.page_id}:{block_key}:{index}:{number}"
            at = partial(path, "stops", "stops", ref)
            stop = draft.add_row("stops", "stops", ref, {"started_at": None, "ended_at": None, "motif": None, "note": None, "corrective_action": None})
            draft.see(at("started_at"), begin_cell)
            draft.see(at("ended_at"), finish_cell)
            if begin is not None:
                stop["started_at"] = draft.ctx.at(begin.value)
                if not begin.sure:
                    draft.flag(at("started_at"), "lookalike")
            elif begin_cell.text.strip():
                draft.flag(at("started_at"), "unreadable")
            if finish is not None:
                stop["ended_at"] = draft.ctx.at(finish.value)
                if not finish.sure:
                    draft.flag(at("ended_at"), "lookalike")
            if how:
                draft.flag(at("started_at"), how)
            stop["note"] = draft.text(at("note"), panne)
            stop["corrective_action"] = draft.text(at("corrective_action"), action)
            stop["motif"] = draft.code(at("motif"), "downtime_motif", panne, quiet=True)


def map_silo(page: PageRead, draft: Draft, side: str) -> None:
    for phase, key in (("start", "silo_start"), ("end", "silo_end")):
        block = page.block(key)
        row = next((r for r in block.rows if not r.is_blank()), None) if block else None
        if row is None:
            continue
        ref = f"{page.page_id}:{key}:0"
        at = partial(path, "silo", "states", ref)
        state = draft.add_row("silo", "states", ref, {"side": side, "phase": phase, "format": None, "lot_number": None, "level_percent": None, "line_state": None})
        state["format"] = draft.text(at("format"), row.cell("format"))
        draft.lot(at("lot_number"), row.cell("lot"), state, "lot_number")
        state["level_percent"] = draft.percent(at("level_percent"), row.cell("level"))
        state["line_state"] = draft.code(at("line_state"), "line_state", row.cell("line_state"))
