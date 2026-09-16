from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from core.domain.result import Err, Ok, Result

# Quarantine is not optional: product goes into a blocked location the moment it is
# pulled and leaves it on disposition. `raised -> quarantined` is therefore a step,
# not a formality — it is the point at which the goods stop being sellable.
NC_TRANSITIONS = {
    "raised": {"quarantined"},
    "quarantined": {"dispositioned"},
    "dispositioned": {"closed"},
    "closed": set(),
}

VALID_SEVERITIES = {"minor", "major", "critical"}

# What a rejected packet breaks down into.
VALID_COMPONENTS = {"product", "film", "carton", "tape"}

# Where each component goes. `dechet` is recorded, never deducted a second time —
# film, carton and tape already left stock when the conditionnement report was
# validated, and deducting them again would understate packaging every time
# quality does its job.
VALID_DISPOSITIONS = {"regrind", "dechet", "rework", "return_to_stock"}

# Only the pasta can be reground; packaging cannot.
REGRINDABLE_COMPONENTS = {"product"}


@dataclass(frozen=True)
class NonConformity:
    id: str
    reference: str
    of_id: str
    product_id: str
    quantity: float
    source_location_id: str
    defect_type: str
    severity: str
    status: str
    quality_report_id: str | None = None
    quarantine_location_id: str | None = None
    description: str | None = None
    corrective_action: str | None = None
    raised_by: str | None = None
    raised_at: datetime.datetime | None = None
    closed_by: str | None = None
    closed_at: datetime.datetime | None = None


@dataclass(frozen=True)
class DispositionLine:
    component: str
    disposition: str
    quantity: float
    note: str | None = None


def transition_non_conformity(non_conformity: NonConformity, new_status: str) -> Result[NonConformity]:
    if new_status not in NC_TRANSITIONS.get(non_conformity.status, set()):
        return Err("INVALID_TRANSITION", f"cannot move non-conformity from {non_conformity.status} to {new_status}")
    return Ok(replace(non_conformity, status=new_status))


def validate_non_conformity(
    *, product_id: str, quantity: float, source_location_id: str, defect_type: str, severity: str
) -> Result[None]:
    if not product_id.strip():
        return Err("MISSING_PRODUCT", "a non-conformity must name the product pulled")
    if quantity <= 0:
        return Err("INVALID_QUANTITY", "the quantity pulled must be positive")
    if not source_location_id.strip():
        return Err("MISSING_LOCATION", "a non-conformity must say where the product was pulled from")
    if not defect_type.strip():
        return Err("MISSING_DEFECT_TYPE", "a non-conformity must name the defect")
    if severity not in VALID_SEVERITIES:
        return Err("INVALID_SEVERITY", f"severity must be one of {sorted(VALID_SEVERITIES)}")
    return Ok(None)


def validate_disposition_lines(lines: tuple[DispositionLine, ...]) -> Result[None]:
    """Check that the breakdown of a rejected packet makes physical sense."""
    if not lines:
        return Err("NO_DISPOSITION_LINES", "a disposition must say where each component went")

    seen: set[tuple[str, str]] = set()
    for line in lines:
        if line.component not in VALID_COMPONENTS:
            return Err("INVALID_COMPONENT", f"component must be one of {sorted(VALID_COMPONENTS)}")
        if line.disposition not in VALID_DISPOSITIONS:
            return Err("INVALID_DISPOSITION", f"disposition must be one of {sorted(VALID_DISPOSITIONS)}")
        if line.quantity <= 0:
            return Err("INVALID_QUANTITY", "every disposition line needs a positive quantity")
        if line.disposition == "regrind" and line.component not in REGRINDABLE_COMPONENTS:
            return Err("NOT_REGRINDABLE", f"{line.component} cannot be reground — only the product can")
        key = (line.component, line.disposition)
        if key in seen:
            return Err("DUPLICATE_LINE", f"{line.component} already has a {line.disposition} line")
        seen.add(key)
    return Ok(None)
