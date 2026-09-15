from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

VALID_CATEGORIES = {"raw_material", "semi_finished", "packaging_component", "finished_good"}
VALID_PACKAGING_FORMATS = {"packet", "carton", "sac"}


@dataclass(frozen=True)
class ProductClassification:
    product_id: str
    category: str
    is_regrind: bool
    packaging_format: str | None = None
    is_water: bool = False


def validate_classification(
    category: str, is_regrind: bool, packaging_format: str | None = None, is_water: bool = False
) -> Result[None]:
    if category not in VALID_CATEGORIES:
        return Err("INVALID_CATEGORY", f"category must be one of {sorted(VALID_CATEGORIES)}")
    if is_regrind and category != "raw_material":
        return Err("REGRIND_FLAG_INVALID", "is_regrind only applies to raw_material products")
    if is_water and category != "raw_material":
        return Err("WATER_FLAG_INVALID", "is_water only applies to raw_material products")
    if is_regrind and is_water:
        return Err("REGRIND_WATER_CONFLICT", "a product cannot be both regrind and water/humidity")
    if packaging_format is not None:
        if category != "finished_good":
            return Err("PACKAGING_FORMAT_INVALID", "packaging_format only applies to finished_good products")
        if packaging_format not in VALID_PACKAGING_FORMATS:
            return Err("INVALID_PACKAGING_FORMAT", f"packaging_format must be one of {sorted(VALID_PACKAGING_FORMATS)}")
    return Ok(None)
