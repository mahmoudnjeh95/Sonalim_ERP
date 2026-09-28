"""Reading clock-device exports with a saved profile, without a database."""
from __future__ import annotations

import datetime as dt

import pytest

from core.domain.result import Err, Ok
from modules.hr.domain.clock_csv import ClockProfile, parse_clock_csv, validate_profile

PROFILE = ClockProfile(
    delimiter=";", has_header=True, badge_column="Badge", timestamp_column="DateHeure",
    timestamp_format="%d/%m/%Y %H:%M", direction_column="Etat", in_values=("Entrée", "IN"), out_values=("Sortie", "OUT"),
)


def _rows(result):
    assert isinstance(result, Ok), result
    return [(row.line_no, row.badge_no, row.punched_at, row.direction, row.error_code) for row in result.value]


def test_a_header_file_is_read_by_column_name_whatever_the_case_of_the_values():
    content = "Badge;DateHeure;Etat\nB001;03/08/2026 06:55;Entrée\nB001;03/08/2026 15:05;sortie\n"
    assert _rows(parse_clock_csv(content, PROFILE)) == [
        (2, "B001", dt.datetime(2026, 8, 3, 6, 55), "in", None),
        (3, "B001", dt.datetime(2026, 8, 3, 15, 5), "out", None),
    ]


def test_an_excel_export_with_bom_and_crlf_is_read():
    content = "﻿Badge;DateHeure;Etat\r\nB001;03/08/2026 06:55;IN\r\n\r\nB002;03/08/2026 07:02;OUT\r\n"
    assert _rows(parse_clock_csv(content, PROFILE)) == [
        (2, "B001", dt.datetime(2026, 8, 3, 6, 55), "in", None),
        (4, "B002", dt.datetime(2026, 8, 3, 7, 2), "out", None),
    ]


def test_a_headerless_file_uses_positions_from_one_and_a_separate_time_column():
    profile = ClockProfile(
        delimiter=",", has_header=False, badge_column="2", timestamp_column="3", time_column="4",
        timestamp_format="%Y-%m-%d %H:%M:%S",
    )
    content = "1,0042,2026-08-03,23:01:10\n2,0042,2026-08-04,07:02:00\n"
    assert _rows(parse_clock_csv(content, profile)) == [
        (1, "0042", dt.datetime(2026, 8, 3, 23, 1, 10), "unknown", None),  # leading zeros kept
        (2, "0042", dt.datetime(2026, 8, 4, 7, 2), "unknown", None),
    ]


def test_bad_rows_are_flagged_not_dropped():
    content = (
        "Badge;DateHeure;Etat\n"
        ";03/08/2026 07:00;IN\n"  # no badge
        "B002;32/08/2026 07:00;IN\n"  # no 32 August
        "B003;03/08/2026 07:00;Pause\n"  # unknown in/out value: not an error
        "B004\n"  # line too short
        "B005;03/08/2026 07:00:15;IN\n"  # seconds the profile does not expect
    )
    result = parse_clock_csv(content, PROFILE)
    assert [(line, error) for line, _, _, _, error in _rows(result)] == [
        (2, "MISSING_BADGE"), (3, "BAD_TIMESTAMP"), (4, None), (5, "MISSING_COLUMN"), (6, "BAD_TIMESTAMP"),
    ]
    assert result.value[2].direction == "unknown"


def test_a_punch_repeated_in_the_file_is_flagged_on_its_second_line():
    content = "Badge;DateHeure;Etat\nB001;03/08/2026 07:00;IN\nB001;03/08/2026 07:00;IN\n"
    assert [error for *_, error in _rows(parse_clock_csv(content, PROFILE))] == [None, "DUPLICATE_PUNCH"]


def test_a_missing_header_column_refuses_the_whole_file():
    result = parse_clock_csv("Badge;Date\nB001;03/08/2026 07:00\n", PROFILE)
    assert isinstance(result, Err) and result.code == "CLOCK_COLUMN_MISSING" and "DateHeure" in result.message_fr


@pytest.mark.parametrize("content", ["", "Badge;DateHeure;Etat\n", "Badge;DateHeure;Etat\n\n\n"])
def test_a_file_without_punches_is_refused(content):
    result = parse_clock_csv(content, PROFILE)
    assert isinstance(result, Err) and result.code == "CLOCK_FILE_EMPTY" and result.message_fr


def test_profile_validation():
    good = dict(
        code="ZK", name="Entrée", delimiter=";", has_header=True, badge_column="Badge", timestamp_column="DateHeure",
        timestamp_format="%d/%m/%Y %H:%M", time_column=None, direction_column=None,
    )
    assert isinstance(validate_profile(**good), Ok)
    for change in ({"delimiter": ";;"}, {"code": " "}, {"has_header": False}, {"timestamp_format": "dd/mm/yyyy"}, {"badge_column": ""}):
        result = validate_profile(**{**good, **change})
        assert isinstance(result, Err) and result.code == "INVALID_CLOCK_PROFILE" and result.message_fr
