#!/usr/bin/env python3
"""Decide which database dumps to delete (grandfather-father-son retention).

Reads file names on stdin, one per line, and prints the ones to delete. Only names of
the form ``<prefix>_YYYYMMDDTHHMMSSZ.dump`` are considered; anything else is left alone.

A dump is kept when it is the newest dump of one of:
  * the last ``--keep-daily`` days that have a dump,
  * the last ``--keep-weekly`` ISO weeks that have a dump,
  * the last ``--keep-monthly`` months that have a dump.

Counting periods *that have a dump* (not calendar periods back from today) means a
stretch with no backups never empties the folder. The newest dump is always kept.

Standard library only: it runs with the host's python3, outside the app image.

    ls /backups | python3 retention.py --prefix erp --keep-daily 14 --keep-weekly 8 --keep-monthly 12
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from typing import Callable, Iterable

_STAMP = r"(\d{8}T\d{6}Z)"


def parse_stamp(name: str, prefix: str) -> datetime | None:
    match = re.fullmatch(re.escape(prefix) + "_" + _STAMP + r"\.dump", name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _newest_per_period(
    dumps: list[tuple[datetime, str]], period: Callable[[datetime], object], count: int
) -> set[str]:
    """Newest dump of each of the ``count`` most recent periods. ``dumps`` is newest first."""
    keep: set[str] = set()
    seen: list[object] = []
    for stamp, name in dumps:
        key = period(stamp)
        if key in seen:
            continue
        if len(seen) >= count:
            break
        seen.append(key)
        keep.add(name)
    return keep


def to_delete(
    names: Iterable[str], prefix: str, keep_daily: int, keep_weekly: int, keep_monthly: int
) -> list[str]:
    dumps = sorted(
        ((stamp, name) for name in names if (stamp := parse_stamp(name, prefix)) is not None),
        reverse=True,
    )
    if not dumps:
        return []
    keep = {dumps[0][1]}
    keep |= _newest_per_period(dumps, lambda s: s.date(), keep_daily)
    keep |= _newest_per_period(dumps, lambda s: s.isocalendar()[:2], keep_weekly)
    keep |= _newest_per_period(dumps, lambda s: (s.year, s.month), keep_monthly)
    return sorted(name for _, name in dumps if name not in keep)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default="erp")
    parser.add_argument("--keep-daily", type=int, default=14)
    parser.add_argument("--keep-weekly", type=int, default=8)
    parser.add_argument("--keep-monthly", type=int, default=12)
    args = parser.parse_args(argv)
    if min(args.keep_daily, args.keep_weekly, args.keep_monthly) < 0:
        parser.error("keep counts must be >= 0")
    names = [line.strip().rsplit("/", 1)[-1] for line in sys.stdin if line.strip()]
    for name in to_delete(names, args.prefix, args.keep_daily, args.keep_weekly, args.keep_monthly):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
