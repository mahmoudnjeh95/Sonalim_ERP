"""Rules of a shift report and its sections. Pure: no database, no I/O.

A shift report is one team's claim about one line, one day, one shift, split into
sections that are saved and submitted one by one. The validator approves the whole
shift at once (that lives in the service); everything here is about how a section
moves and what that does to the shift.
"""
from __future__ import annotations

from typing import Iterable, Sequence

# The paper fiches' order, which is the order the screen shows them in. A new
# section (bobines, paramètres) is added here and gets its own edit permission.
SECTION_KEYS: tuple[str, ...] = (
    "runs",
    "waste_production",
    "stops",
    "silo",
    "staffing",
    "packing",
    "packet_checks",
    "waste_packing",
    "energy",
)

_DONE = {"submitted", "nothing_to_report"}


def permission_for_section(section_key: str) -> str:
    """The permission that lets a user change one section.

    Kept per section, not per report, because the teams that own sections differ:
    fabrication does not edit the packing table. Roles bundle these same keys.
    """
    if section_key not in SECTION_KEYS:
        raise ValueError(f"unknown shift report section: {section_key!r}")
    return f"production.shift.edit.{section_key}"


def status_after_save(section_status: str) -> tuple[str, bool]:
    """(new status, whether this save is an edit of an already submitted section).

    Saving a section that was never submitted, was returned, or was declared
    empty makes it a draft. Saving a submitted section leaves it submitted: the
    team keeps working on handed-in figures and every save is a revision, so the
    validator always sees the latest one.
    """
    if section_status == "submitted":
        return "submitted", True
    return "draft", False


def can_submit(section_status: str) -> bool:
    """An empty section cannot be submitted (say "nothing to report" instead)."""
    return section_status in ("draft", "returned")


def can_declare_nothing(section_status: str) -> bool:
    """A team may always say a section has nothing in it; the service clears its rows."""
    return section_status in ("empty", "draft", "returned", "submitted", "nothing_to_report")


def derive_shift_status(current: str, section_statuses: Iterable[str]) -> str:
    """The shift's status implied by its sections' statuses.

    Validation freezes the shift. Otherwise one returned section returns the shift,
    and the shift is submitted once every section is submitted or declared empty.
    """
    if current == "validated":
        return "validated"
    statuses = list(section_statuses)
    if any(s == "returned" for s in statuses):
        return "returned"
    if statuses and all(s in _DONE for s in statuses):
        return "submitted"
    return "open"


def split_proportionally(total: float, weights: Sequence[float]) -> list[float]:
    """Share `total` across runs in proportion to `weights` (their production minutes).

    Every share but the last is rounded to six decimals and the last takes what is
    left, so the shares add up to the total exactly. When no run recorded any
    minutes there is nothing to weigh by, so the first run takes everything.
    """
    if not weights:
        return []
    weight_sum = sum(weights)
    if total == 0:
        return [0 for _ in weights]
    if weight_sum <= 0:
        return [total] + [0 for _ in weights[1:]]
    shares = [round(total * w / weight_sum, 6) for w in weights[:-1]]
    return [*shares, round(total - sum(shares), 9)]
