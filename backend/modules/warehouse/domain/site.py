from __future__ import annotations

from core.domain.result import Err, Ok, Result


def validate_site_code(code: str) -> Result[str]:
    code = code.strip()
    if not code:
        return Err("INVALID_CODE", "site code is required", "le code du site est obligatoire")
    return Ok(code)


def validate_reparent(
    location_id: str,
    new_parent_id: str | None,
    parents_by_id: dict[str, str | None],
) -> Result[None]:
    """Rejects a reparent that would make a location its own ancestor.

    `parents_by_id` maps every location id in the same site to its current
    parent_location_id, so the chain from `new_parent_id` back to the root can
    be walked without another database round trip.
    """
    if new_parent_id is None:
        return Ok(None)
    if new_parent_id == location_id:
        return Err(
            "INVALID_PARENT", "a location cannot be its own parent", "un emplacement ne peut pas être son propre parent"
        )
    seen = {location_id}
    current: str | None = new_parent_id
    while current is not None:
        if current in seen:
            return Err(
                "INVALID_PARENT",
                "this would create a cycle in the location hierarchy",
                "cela créerait un cycle dans la hiérarchie des emplacements",
            )
        seen.add(current)
        current = parents_by_id.get(current)
    return Ok(None)
