"""A run compared with the previous month's approved run, employee by employee.

No threshold decides what is "abnormal": rows are sorted by the size of the net change and the
payroll officer judges (every figure comes from a recorded payslip).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)


@dataclass(frozen=True)
class VarianceRow:
    employee_id: str
    employee_no: str
    full_name: str
    previous_gross: Decimal | None
    current_gross: Decimal | None
    previous_net: Decimal | None
    current_net: Decimal | None

    @property
    def change(self) -> str:
        if self.previous_net is None:
            return "new"
        if self.current_net is None:
            return "left"
        unchanged = self.previous_gross == self.current_gross and self.previous_net == self.current_net
        return "same" if unchanged else "changed"

    @property
    def delta_gross(self) -> Decimal:
        return (self.current_gross or ZERO) - (self.previous_gross or ZERO)

    @property
    def delta_net(self) -> Decimal:
        return (self.current_net or ZERO) - (self.previous_net or ZERO)


def compare(current: Sequence[dict[str, Any]], previous: Sequence[dict[str, Any]]) -> list[VarianceRow]:
    now = {row["employee_id"]: row for row in current}
    before = {row["employee_id"]: row for row in previous}
    rows: list[VarianceRow] = []
    for employee_id in now.keys() | before.keys():
        this_month, last_month = now.get(employee_id), before.get(employee_id)
        label = this_month or last_month
        rows.append(VarianceRow(
            employee_id=employee_id, employee_no=label["employee_no"], full_name=label["full_name"],
            previous_gross=None if last_month is None else last_month["gross"],
            current_gross=None if this_month is None else this_month["gross"],
            previous_net=None if last_month is None else last_month["net"],
            current_net=None if this_month is None else this_month["net"],
        ))
    return sorted(rows, key=lambda row: (-abs(row.delta_net), row.full_name))
