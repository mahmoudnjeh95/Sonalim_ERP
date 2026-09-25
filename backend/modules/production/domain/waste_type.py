"""The déchet kinds a plant defines for itself.

Built-in kinds live in `production_report.WASTE_CATEGORIES_BY_REPORT_TYPE`; this
is the rule for the ones an administrator adds on top. A kind is a name and the
one report it is entered on -- nothing else, so there is nothing here to judge.
"""
from __future__ import annotations

from core.domain.result import Err, Ok, Result

# The reports a déchet line can sit on. Same two strings the report itself uses.
WASTE_TYPE_REPORT_TYPES = ("daily", "conditionnement")


def validate_waste_type(*, name: str, report_type: str) -> Result[str]:
    """The trimmed name, or why the kind cannot exist."""
    trimmed = name.strip()
    if not trimmed:
        return Err("INVALID_NAME", "a waste type needs a name", "un type de déchet a besoin d'un nom")
    if report_type not in WASTE_TYPE_REPORT_TYPES:
        return Err(
            "INVALID_REPORT_TYPE",
            f"report_type must be one of {list(WASTE_TYPE_REPORT_TYPES)}",
            f"report_type doit être l'un de {list(WASTE_TYPE_REPORT_TYPES)}",
        )
    return Ok(trimmed)
