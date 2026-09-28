"""Reading a clock-device CSV export with a saved device profile. Pure: no database.

A row that cannot be read is kept with an error code (the reviewer sees it); only a file
whose header lacks a profile column, or that holds no punch at all, is refused whole.
"""
from __future__ import annotations

import csv
import datetime
import io
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

_EMPTY = Err("CLOCK_FILE_EMPTY", "the file has no punch rows", "le fichier ne contient aucun pointage")


@dataclass(frozen=True)
class ClockProfile:
    delimiter: str
    has_header: bool
    badge_column: str
    timestamp_column: str
    timestamp_format: str
    time_column: str | None = None
    direction_column: str | None = None
    in_values: tuple[str, ...] = ()
    out_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedRow:
    line_no: int
    raw: str
    badge_no: str | None
    punched_at: datetime.datetime | None
    direction: str
    error_code: str | None


def validate_profile(
    *,
    code: str,
    name: str,
    delimiter: str,
    has_header: bool,
    badge_column: str,
    timestamp_column: str,
    timestamp_format: str,
    time_column: str | None,
    direction_column: str | None,
) -> Result[None]:
    if not code.strip() or not name.strip():
        return Err("INVALID_CLOCK_PROFILE", "profile code and name are required", "le code et le nom du profil sont obligatoires")
    if len(delimiter) != 1:
        return Err("INVALID_CLOCK_PROFILE", "the separator is a single character", "le séparateur est un seul caractère")
    if not badge_column.strip() or not timestamp_column.strip():
        return Err("INVALID_CLOCK_PROFILE", "the badge and date/time columns are required", "les colonnes badge et date/heure sont obligatoires")
    columns = [column for column in (badge_column, timestamp_column, time_column, direction_column) if column]
    if not has_header and not all(column.strip().isdigit() and int(column) >= 1 for column in columns):
        return Err(
            "INVALID_CLOCK_PROFILE",
            "without a header line, columns are positions starting at 1",
            "sans ligne d'en-tête, les colonnes sont des positions à partir de 1",
        )
    if "%" not in timestamp_format:
        return Err(
            "INVALID_CLOCK_PROFILE",
            "the date/time format uses codes such as %d/%m/%Y %H:%M",
            "le format date/heure utilise des codes comme %d/%m/%Y %H:%M",
        )
    return Ok(None)


def _position(column: str, header: list[str] | None) -> int | None:
    if header is None:
        return int(column) - 1
    wanted = column.strip().casefold()
    return next((index for index, name in enumerate(header) if name.strip().casefold() == wanted), None)


def parse_clock_csv(content: str, profile: ClockProfile) -> Result[list[ParsedRow]]:
    reader = csv.reader(io.StringIO(content.lstrip("﻿"), newline=""), delimiter=profile.delimiter)
    header: list[str] | None = None
    if profile.has_header:
        header = next(reader, None)
        if header is None:
            return _EMPTY
    wanted = {"badge": profile.badge_column, "timestamp": profile.timestamp_column}
    if profile.time_column:
        wanted["time"] = profile.time_column
    if profile.direction_column:
        wanted["direction"] = profile.direction_column
    positions: dict[str, int] = {}
    for role, column in wanted.items():
        index = _position(column, header)
        if index is None:
            return Err("CLOCK_COLUMN_MISSING", f"column {column!r} is not in the file header", f"la colonne {column!r} est absente de l'en-tête du fichier")
        positions[role] = index
    needed = max(positions.values())
    ins = {value.strip().casefold() for value in profile.in_values}
    outs = {value.strip().casefold() for value in profile.out_values}
    rows: list[ParsedRow] = []
    seen: set[tuple[str, datetime.datetime]] = set()
    for record in reader:
        line_no = reader.line_num
        if not any(cell.strip() for cell in record):
            continue
        raw = profile.delimiter.join(record)
        if len(record) <= needed:
            rows.append(ParsedRow(line_no, raw, None, None, "unknown", "MISSING_COLUMN"))
            continue
        badge = record[positions["badge"]].strip() or None
        text = record[positions["timestamp"]].strip()
        if "time" in positions:
            text = f"{text} {record[positions['time']].strip()}"
        try:
            punched_at: datetime.datetime | None = datetime.datetime.strptime(text, profile.timestamp_format)
        except ValueError:
            punched_at = None
        direction = "unknown"
        if "direction" in positions:
            value = record[positions["direction"]].strip().casefold()
            direction = "in" if value in ins else "out" if value in outs else "unknown"
        error = None
        if badge is None:
            error = "MISSING_BADGE"
        elif punched_at is None:
            error = "BAD_TIMESTAMP"
        elif (badge, punched_at) in seen:
            error = "DUPLICATE_PUNCH"
        else:
            seen.add((badge, punched_at))
        rows.append(ParsedRow(line_no, raw, badge, punched_at, direction, error))
    if not rows:
        return _EMPTY
    return Ok(rows)
