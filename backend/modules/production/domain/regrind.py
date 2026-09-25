from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

# Where a scrap record came from. filling_dosing (versement) and cutting (découpe)
# are the two hand-entered stages; daily_report is written by the service when a
# daily report validates with rebroyat above zero, which is how scrap_records
# turns from a typed-in record into a derived ledger. The non-conformity sources
# join this set with the qc module.
VALID_SCRAP_TYPES = {"filling_dosing", "cutting", "daily_report", "shift_run", "non_conformity"}


@dataclass(frozen=True)
class ScrapRecord:
    id: str
    work_order_id: str | None
    operation_step_id: str | None
    scrap_type: str
    product_id: str
    quantity: float
    is_reground: bool
    work_center_id: str | None = None
    source_note: str | None = None
    # The OFR (regrind order) that consumed this scrap; None while it is still available.
    regrind_work_order_id: str | None = None


def validate_scrap(
    *, scrap_type: str, quantity: float, work_order_id: str | None, source_note: str | None
) -> Result[None]:
    if scrap_type not in VALID_SCRAP_TYPES:
        return Err(
            "INVALID_SCRAP_TYPE",
            f"scrap_type must be one of {sorted(VALID_SCRAP_TYPES)}",
            f"scrap_type doit être l'un de {sorted(VALID_SCRAP_TYPES)}",
        )
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "scrap quantity must be positive", "la quantité de rebut doit être positive")
    if not (work_order_id or (source_note and source_note.strip())):
        return Err("MISSING_SOURCE", "either a work order or a source note is required", "un OF ou une note de source est obligatoire")
    return Ok(None)


def validate_team_assignment(team: str) -> Result[None]:
    if not team.strip():
        return Err("MISSING_TEAM", "a regrind batch needs a team to assign it to", "un lot de rebroyat a besoin d'une équipe à qui l'assigner")
    return Ok(None)
