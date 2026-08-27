from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result


@dataclass(frozen=True)
class ResourceType:
    id: str
    code: str
    name: str
    unit: str


def validate_resource_type(*, code: str, name: str, unit: str) -> Result[None]:
    if not code.strip():
        return Err("INVALID_CODE", "code is required")
    if not name.strip():
        return Err("INVALID_NAME", "name is required")
    if not unit.strip():
        return Err("INVALID_UNIT", "unit is required")
    return Ok(None)


@dataclass(frozen=True)
class DailyConsumption:
    id: str
    consumption_date: str
    resource_type_id: str
    quantity: float
    note: str | None


def validate_consumption(*, quantity: float) -> Result[None]:
    if quantity < 0:
        return Err("INVALID_QUANTITY", "quantity must be >= 0")
    return Ok(None)


@dataclass(frozen=True)
class WorkOrderConsumption:
    id: str
    work_order_id: str
    resource_type_id: str
    quantity: float
    note: str | None
