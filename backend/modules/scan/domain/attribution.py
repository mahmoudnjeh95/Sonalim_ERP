"""Does a photographed fiche belong to the shift the user picked?

The user always picks line, date and shift first; each page's own header is compared
with that choice. A different date, start hour or ticked line puts the page aside as
another shift's -- the example upload mixed a team D morning fiche with a team A
afternoon bobines sheet. A header with neither a date nor an hour read is "unknown":
included, but nothing on it confirms the shift.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Mapping

from modules.scan.domain.ocr_result import EMPTY_CELL, PageRead, ReadCell
from modules.scan.domain.text import normalize, parse_date, team_and_hours


@dataclass(frozen=True)
class Selection:
    report_date: datetime.date
    shift_start: datetime.time
    line_label: str | None


@dataclass(frozen=True)
class Attribution:
    verdict: str  # this_shift | other_shift | unknown
    reasons: tuple[str, ...]  # date | hours | line
    read: dict


def line_label_of(*names: str | None) -> str | None:
    """PC or PL when a line's code or name says so -- the box ticked on the fiche."""
    for name in names:
        words = normalize(name).split()
        if "pc" in words:
            return "PC"
        if "pl" in words:
            return "PL"
    return None


def header_of_page(page: PageRead) -> Mapping[str, ReadCell]:
    """The cells that say whose fiche it is.

    The bobines sheet has no header: every row names its date, team and working hours,
    so its first written row stands for the page.
    """
    if page.form_type != "bobines":
        return page.header
    block = page.block("changes")
    row = next((r for r in block.rows if not r.is_blank()), None) if block else None
    if row is None:
        return {}
    team, hours = row.cell("team"), row.cell("hours")
    return {"date": row.cell("date"), "team_hours": ReadCell(f"{team.text} {hours.text}".strip(), min(team.confidence, hours.confidence))}


def _ticked_line(header: Mapping[str, ReadCell]) -> str | None:
    pc = bool(header.get("line_pc", EMPTY_CELL).text.strip())
    pl = bool(header.get("line_pl", EMPTY_CELL).text.strip())
    if pc == pl:
        return None
    return "PC" if pc else "PL"


def attribute(header: Mapping[str, ReadCell], selection: Selection) -> Attribution:
    date = parse_date(header.get("date", EMPTY_CELL).text).value
    team, hours = team_and_hours(header.get("team_hours", EMPTY_CELL).text)
    line = _ticked_line(header)
    reasons: list[str] = []
    if date is not None and date != selection.report_date:
        reasons.append("date")
    if hours is not None and hours.hour != selection.shift_start.hour:
        reasons.append("hours")
    if line is not None and selection.line_label is not None and line != selection.line_label:
        reasons.append("line")
    read = {
        "date": date.isoformat() if date else None,
        "team": team,
        "hours_from": hours.strftime("%H:%M") if hours else None,
        "line": line,
    }
    if reasons:
        return Attribution("other_shift", tuple(reasons), read)
    if date is None and hours is None:
        return Attribution("unknown", (), read)
    return Attribution("this_shift", (), read)
