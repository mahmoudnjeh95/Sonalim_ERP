"""Which machine of a line a stage names, and what a silo reading does to machine status."""
from __future__ import annotations

from collections.abc import Sequence

# (machine id, production stage, status) as Maintenance's registry records them.
Machine = tuple[str, str | None, str]

# The silo has two sides; each side reads the stages that work on it.
SIDE_STAGES = {"production": ("versement", "extrusion"), "packing": ("conditionnement",)}
STATE_TARGET = {"stopped": "down", "running": "operational"}


def pick_stage_machine(machines: Sequence[Machine], stage: str) -> str | None:
    """The machine at `stage`, only when the line has exactly one there."""
    at_stage = [machine_id for machine_id, machine_stage, _ in machines if machine_stage == stage]
    return at_stage[0] if len(at_stage) == 1 else None


def silo_machine_changes(*, side: str, line_state: str | None, machines: Sequence[Machine]) -> list[tuple[str, str]]:
    """`(machine_id, new_status)` for the machines a silo reading moves.

    A machine in `maintenance` belongs to Maintenance and is left alone, as is one already
    in the target status. An unknown state (or none) changes nothing.
    """
    target = STATE_TARGET.get(line_state or "")
    stages = SIDE_STAGES.get(side, ())
    if target is None:
        return []
    return [
        (machine_id, target)
        for machine_id, stage, status in machines
        if stage in stages and status not in ("maintenance", target)
    ]
