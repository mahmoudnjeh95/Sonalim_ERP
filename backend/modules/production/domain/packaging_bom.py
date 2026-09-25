from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

PACKAGING_BOM_VALID_TRANSITIONS = {
    "draft": {"active"},
    "active": {"archived"},
    "archived": set(),
}


@dataclass(frozen=True)
class PackagingBomLine:
    component_product_id: str
    quantity_per_unit: float


@dataclass(frozen=True)
class PackagingBom:
    id: str
    target_product_id: str
    version: int
    status: str
    lines: tuple[PackagingBomLine, ...]


def validate_bom_lines(lines: tuple[PackagingBomLine, ...]) -> Result[None]:
    if not lines:
        return Err("EMPTY_BOM", "a packaging BOM must have at least one line", "une nomenclature d'emballage doit avoir au moins une ligne")
    for line in lines:
        if line.quantity_per_unit <= 0:
            return Err(
                "INVALID_QUANTITY",
                f"quantity_per_unit must be positive for {line.component_product_id}",
                f"quantity_per_unit doit être positif pour {line.component_product_id}",
            )
    return Ok(None)


def transition_bom(bom: PackagingBom, new_status: str) -> Result[PackagingBom]:
    if new_status not in PACKAGING_BOM_VALID_TRANSITIONS.get(bom.status, set()):
        return Err(
            "INVALID_TRANSITION",
            f"cannot move packaging BOM from {bom.status} to {new_status}",
            f"impossible de faire passer la nomenclature d'emballage de {bom.status} à {new_status}",
        )
    return Ok(
        PackagingBom(
            id=bom.id,
            target_product_id=bom.target_product_id,
            version=bom.version,
            status=new_status,
            lines=bom.lines,
        )
    )
