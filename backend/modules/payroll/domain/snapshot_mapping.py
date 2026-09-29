"""hr's contract-shaped dicts -> engine inputs. The only place that knows the contract's key names
(docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md, "Phase 1 → Phase 3")."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from modules.payroll.domain.inputs import ContractComponent, EmployeeInput, PresenceInput

PRESENCE_FIELDS = (
    "scheduled_days", "worked_days", "unpaid_absence_days", "paid_leave_days", "sick_days", "holiday_days",
    "holidays_worked_days", "rest_days_worked", "ot_minutes_day", "ot_minutes_night", "ot_minutes_rest_holiday",
)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def employee_input(snapshot: dict[str, Any]) -> EmployeeInput:
    contract = snapshot["contract"]
    return EmployeeInput(
        employee_id=snapshot["employee_id"],
        base_salary=Decimal(str(contract["base_salary"])),
        pay_frequency=contract["pay_frequency"],
        hire_date=snapshot["hire_date"],
        contract_start=contract["start_date"],
        contract_end=contract.get("end_date"),
        termination_date=snapshot.get("termination_date"),
        tax_dependants=int(snapshot.get("tax_dependants") or 0),
        components=tuple(
            ContractComponent(component_code=item["component_code"], amount=_decimal(item.get("amount")), rate=_decimal(item.get("rate")))
            for item in contract.get("components") or []
        ),
    )


def presence_input(summary: dict[str, Any] | None) -> PresenceInput:
    if summary is None:
        return PresenceInput()
    return PresenceInput(**{field: int(summary.get(field) or 0) for field in PRESENCE_FIELDS})
