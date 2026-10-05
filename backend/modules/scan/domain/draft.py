"""The proposal being built from the read pages.

Rows are collected per section and part in the payload shape `save_section` takes,
each carrying `_scan_ref`. Beside them, per field path: where the value was read
(`sources`), why a person should look at it (`flags`), and, for coded values, what was
written and what it resolved to (`coded`, the base for learning aliases on apply).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Mapping

from modules.scan.domain.ocr_result import ReadCell
from modules.scan.domain.text import (
    Parsed, decode_lot, is_short_lot, parse_date, parse_decimal, parse_int, parse_lot, parse_percent, parse_time, team_letter,
)
from modules.scan.domain.vocabulary import Vocabulary, resolve

_REASON_FOR_RESOLUTION = {"contained": "partial_match", "ambiguous": "ambiguous", "none": "unresolved"}


def path(section: str, part: str, ref: str, field: str) -> str:
    return f"{section}/{part}/{ref}/{field}"


def header_path(field: str) -> str:
    return path("header", "-", "-", field)


def section_path(section: str) -> str:
    return path(section, "-", "-", "-")


@dataclass(frozen=True)
class ProposalContext:
    report_date: datetime.date
    shift_start: datetime.time
    shift_end: datetime.time
    team: str | None
    default_of_id: str | None
    default_product_id: str | None
    vocabulary: Vocabulary
    aliases: Mapping[tuple[str, str], str]

    def at(self, moment: datetime.time) -> str:
        """The timestamp of a time written on the fiche: the report date, or the next day
        for the early hours of a shift that runs past midnight."""
        day = self.report_date
        if self.shift_end <= self.shift_start and moment < self.shift_start:
            day += datetime.timedelta(days=1)
        return datetime.datetime.combine(day, moment).isoformat(timespec="minutes")


class Draft:
    def __init__(self, ctx: ProposalContext) -> None:
        self.ctx = ctx
        self.accept_score = 0.5
        self.header: dict[str, Any] = {}
        self.sections: dict[str, dict[str, Any]] = {}
        self.flags: dict[str, list[dict]] = {}
        self.sources: dict[str, list[dict]] = {}
        self.coded: dict[str, dict] = {}
        self.set_aside: dict[str, list[dict]] = {}
        self.team_letter_read: str | None = None
        # Packing-side waste lines that came from the fabrication sheet's "Produit fini" block.
        self.fabrication_losses: list[dict] = []
        self._lots: list[tuple[dict, str, str, bool]] = []

    # ---- structure ---------------------------------------------------------

    def rows(self, section: str, part: str) -> list[dict]:
        return self.sections.setdefault(section, {}).setdefault(part, [])

    def add_row(self, section: str, part: str, ref: str, row: dict) -> dict:
        row["_scan_ref"] = ref
        self.rows(section, part).append(row)
        return row

    def single(self, section: str, part: str) -> dict:
        return self.sections.setdefault(section, {}).setdefault(part, {})

    # ---- flags and sources -------------------------------------------------

    def flag(self, at: str, reason: str, detail: str | None = None) -> None:
        entry = {"reason": reason, "detail": detail}
        bucket = self.flags.setdefault(at, [])
        if entry not in bucket:
            bucket.append(entry)

    def see(self, at: str, cell: ReadCell) -> None:
        if not cell.text.strip():
            return
        self.sources.setdefault(at, []).append(
            {"page_id": cell.page_id, "box": list(cell.box) if cell.box else None, "text": cell.text, "confidence": round(cell.confidence, 3)}
        )
        if cell.confidence < self.accept_score:
            self.flag(at, "low_confidence")
        if cell.conflict is not None:
            self.flag(at, "conflicting", cell.conflict)

    def _read(self, at: str, cell: ReadCell, parsed: Parsed) -> Any:
        self.see(at, cell)
        if cell.text.strip() and parsed.value is None:
            self.flag(at, "unreadable")
        elif parsed.value is not None and not parsed.sure:
            self.flag(at, "lookalike")
        return parsed.value

    def text(self, at: str, cell: ReadCell) -> str | None:
        self.see(at, cell)
        return cell.text.strip() or None

    def decimal(self, at: str, cell: ReadCell) -> float | None:
        return self._read(at, cell, parse_decimal(cell.text))

    def percent(self, at: str, cell: ReadCell) -> float | None:
        return self._read(at, cell, parse_percent(cell.text))

    def integer(self, at: str, cell: ReadCell) -> int | None:
        return self._read(at, cell, parse_int(cell.text))

    def time(self, at: str, cell: ReadCell) -> datetime.time | None:
        return self._read(at, cell, parse_time(cell.text))

    def date(self, at: str, cell: ReadCell) -> datetime.date | None:
        return self._read(at, cell, parse_date(cell.text))

    def code(self, at: str, kind: str, cell: ReadCell, *, prefer: str | None = None, quiet: bool = False) -> str | None:
        """A written code turned into a system value; `quiet` for optional fields nobody must check."""
        self.see(at, cell)
        written = cell.text.strip()
        if not written:
            return None
        found = resolve(self.ctx.vocabulary, self.ctx.aliases, kind, written, prefer=prefer)
        self.coded[at] = {"kind": kind, "read_text": written, "value": found.value}
        reason = _REASON_FOR_RESOLUTION.get(found.how)
        if reason and not quiet:
            self.flag(at, reason)
        return found.value

    def lot(self, at: str, cell: ReadCell, row: dict, field: str, *, check: bool = False) -> None:
        """Store a written lot on the row; `check` compares it with the shift once all pages are read."""
        self.see(at, cell)
        parsed = parse_lot(cell.text)
        row[field] = parsed.value
        if parsed.value is None:
            return
        if not parsed.sure:
            self.flag(at, "lot_format")
        self._lots.append((row, field, at, check))

    # ---- after every page --------------------------------------------------

    def finish(self) -> None:
        self._complete_short_lots()
        self._check_lots()
        self._set_aside_losses_counted_twice()

    def _complete_short_lots(self) -> None:
        full = {row[field] for row, field, _, _ in self._lots if row.get(field) and not is_short_lot(row[field])}
        for row, field, at, _ in self._lots:
            if is_short_lot(row.get(field)):
                matches = sorted(lot for lot in full if lot.startswith(row[field]))
                if len(matches) == 1:
                    row[field] = matches[0]
                    self.flag(at, "short_lot")

    def _check_lots(self) -> None:
        expected_letter = team_letter(self.ctx.team) or self.team_letter_read
        for row, field, at, check in self._lots:
            if not check or not row.get(field) or is_short_lot(row[field]):
                continue
            decoded = decode_lot(row[field], self.ctx.report_date)
            if decoded is None:
                continue
            letter, day = decoded
            if day != self.ctx.report_date:
                self.flag(at, "lot_date", day.isoformat())
            if expected_letter and letter != expected_letter:
                self.flag(at, "lot_team", letter)

    def _set_aside_losses_counted_twice(self) -> None:
        """One place per loss: finished product lost is filed on the packing side.

        When the conditionnement sheet of the same session lists finished product lost
        and packed the same lot, the fabrication sheet's "Produit fini" line is most
        likely the same kilos; it is put aside (the user can add it back), not counted twice.
        """
        lines = self.sections.get("waste_packing", {}).get("waste_lines", [])
        packed_lots = {row.get("lot_number") for row in self.sections.get("packing", {}).get("rows", []) if row.get("lot_number")}
        packing_product_lines = [
            row for row in lines if row.get("category") == "product" and all(row is not loss for loss in self.fabrication_losses)
        ]
        if not packing_product_lines:
            return
        for loss in self.fabrication_losses:
            if loss.get("lot_number") in packed_lots:
                lines.remove(loss)
                self.set_aside.setdefault("waste_packing", []).append({"part": "waste_lines", "row": loss, "reason": "same_loss"})

    def to_json(self, pages: dict) -> dict:
        return {
            "header": self.header,
            "sections": self.sections,
            "flags": self.flags,
            "sources": self.sources,
            "coded": self.coded,
            "set_aside": self.set_aside,
            "pages": pages,
        }
