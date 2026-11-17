from datetime import datetime, timedelta, timezone

from retention import parse_stamp, to_delete


def _name(dt: datetime, prefix: str = "erp") -> str:
    return f"{prefix}_{dt.strftime('%Y%m%dT%H%M%SZ')}.dump"


def _nightly(days: int, start: datetime = datetime(2026, 1, 1, 2, 15, tzinfo=timezone.utc)) -> list[str]:
    return [_name(start + timedelta(days=i)) for i in range(days)]


def _kept(names: list[str], **keep: int) -> set[str]:
    return set(names) - set(to_delete(names, "erp", **keep))


def test_parse_stamp_accepts_only_own_pattern():
    assert parse_stamp("erp_20261116T021500Z.dump", "erp") == datetime(2026, 11, 16, 2, 15, tzinfo=timezone.utc)
    assert parse_stamp("erp_20261116T021500Z.dump.sha256", "erp") is None
    assert parse_stamp("erp_20261116T021500Z.dump.partial", "erp") is None
    assert parse_stamp("pre-restore_20261116T021500Z.dump", "erp") is None
    assert parse_stamp("erp_20261399T021500Z.dump", "erp") is None  # not a real date
    assert parse_stamp("sonalim_dev_2026-09-21.dump", "erp") is None


def test_year_of_nightly_dumps_keeps_daily_weekly_monthly():
    names = _nightly(365)  # 2026-01-01 .. 2026-12-31
    kept = _kept(names, keep_daily=14, keep_weekly=8, keep_monthly=12)
    newest = sorted(names)[-1]
    assert newest in kept
    # the 14 most recent days are all kept
    assert set(sorted(names)[-14:]) <= kept
    # 12 months, each represented by its newest dump (last day of the month)
    for month in range(1, 13):
        assert any(n.startswith(f"erp_2026{month:02d}") for n in kept)
    assert "erp_20260131T021500Z.dump" in kept
    assert "erp_20260130T021500Z.dump" not in kept
    # bounded: at most 14 + 8 + 12 files
    assert len(kept) <= 34
    assert len(kept) >= 14 + 1


def test_newest_dump_survives_zero_keep_counts():
    names = _nightly(5)
    assert _kept(names, keep_daily=0, keep_weekly=0, keep_monthly=0) == {sorted(names)[-1]}


def test_several_dumps_one_day_keeps_newest_of_the_day():
    day = datetime(2026, 11, 16, tzinfo=timezone.utc)
    names = [_name(day.replace(hour=h)) for h in (2, 9, 14)]
    assert _kept(names, keep_daily=7, keep_weekly=0, keep_monthly=0) == {_name(day.replace(hour=14))}


def test_gap_in_backups_does_not_empty_the_folder():
    # backups stopped for 60 days, then one more ran: the old daily ones stay
    old = _nightly(10)
    late = _name(datetime(2026, 3, 12, 2, 15, tzinfo=timezone.utc))
    kept = _kept(old + [late], keep_daily=7, keep_weekly=0, keep_monthly=0)
    assert late in kept
    assert len(kept) == 7


def test_foreign_files_are_never_deleted():
    names = _nightly(30) + [
        "pre-restore_20260101T000000Z.dump",
        "erp_20260101T021500Z.dump.sha256",
        "notes.txt",
        "erp_20260102T021500Z.dump.partial",
    ]
    deleted = set(to_delete(names, "erp", keep_daily=3, keep_weekly=0, keep_monthly=0))
    assert deleted
    assert all(n.endswith(".dump") and n.startswith("erp_") for n in deleted)


def test_other_prefix_is_ignored():
    names = _nightly(10) + [_name(datetime(2026, 1, 1, tzinfo=timezone.utc), prefix="erp_dev")]
    deleted = to_delete(names, "erp", keep_daily=1, keep_weekly=0, keep_monthly=0)
    assert all(not n.startswith("erp_dev") for n in deleted)


def test_empty_input():
    assert to_delete([], "erp", 14, 8, 12) == []
