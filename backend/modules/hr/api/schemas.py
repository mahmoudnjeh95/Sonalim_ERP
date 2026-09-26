"""Request bodies of the hr routes. A PATCH body's unset fields mean "leave it as it is" (the
router passes model_dump(exclude_unset=True)); a field sent as null means "clear it"."""
from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    code: str
    name: str
    manager_employee_id: str | None = None


class DepartmentPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    manager_employee_id: str | None = None


class PositionCreate(BaseModel):
    code: str
    title: str
    department_id: str | None = None
    headcount_budget: int | None = None


class PositionPatch(BaseModel):
    code: str | None = None
    title: str | None = None
    department_id: str | None = None
    headcount_budget: int | None = None


class GradeCreate(BaseModel):
    code: str
    category: str
    echelon: str
    base_salary: Decimal
    valid_from: datetime.date


class GradePatch(BaseModel):
    code: str | None = None
    category: str | None = None
    echelon: str | None = None
    base_salary: Decimal | None = None
    valid_from: datetime.date | None = None


class EmployeeCreate(BaseModel):
    employee_no: str
    first_name: str
    last_name: str
    hire_date: datetime.date
    status: str = "active"
    email: str | None = None
    phone: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    user_id: str | None = None
    gender: str | None = None
    birth_date: datetime.date | None = None
    birth_place: str | None = None
    nationality: str | None = None
    national_id: str | None = None
    inps_no: str | None = None
    amo_no: str | None = None
    marital_status: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    badge_no: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    site: str | None = None


class EmployeePatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    hire_date: datetime.date | None = None
    status: str | None = None
    email: str | None = None
    phone: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    user_id: str | None = None
    gender: str | None = None
    birth_date: datetime.date | None = None
    birth_place: str | None = None
    nationality: str | None = None
    national_id: str | None = None
    inps_no: str | None = None
    amo_no: str | None = None
    marital_status: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    badge_no: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    site: str | None = None
    termination_date: datetime.date | None = None
    termination_reason: str | None = None


class DependantCreate(BaseModel):
    kind: str
    name: str
    valid_from: datetime.date
    birth_date: datetime.date | None = None
    dependent_for_tax: bool = False
    valid_to: datetime.date | None = None


class DependantPatch(BaseModel):
    kind: str | None = None
    name: str | None = None
    valid_from: datetime.date | None = None
    birth_date: datetime.date | None = None
    dependent_for_tax: bool = False  # never null: only sent when it changes
    valid_to: datetime.date | None = None


class PaymentMethodBody(BaseModel):
    method: str
    share_percent: Decimal
    is_primary: bool = False
    bank_name: str | None = None
    account_no: str | None = None
    mobile_operator: str | None = None
    mobile_number: str | None = None


class PaymentSetBody(BaseModel):
    valid_from: datetime.date
    methods: list[PaymentMethodBody]


class ComponentBody(BaseModel):
    component_code: str
    amount: Decimal | None = None
    rate: Decimal | None = None  # percent: 10 means 10 %


class ContractCreate(BaseModel):
    employee_id: str
    contract_type: str
    start_date: datetime.date
    base_salary: Decimal
    end_date: datetime.date | None = None
    trial_end_date: datetime.date | None = None
    weekly_hours: Decimal = Decimal("40")
    pay_frequency: str = "monthly"
    position_id: str | None = None
    grade_id: str | None = None
    status: str = "active"
    components: list[ComponentBody] = []


class ContractPatch(BaseModel):
    contract_type: str | None = None
    start_date: datetime.date | None = None
    base_salary: Decimal | None = None
    end_date: datetime.date | None = None
    trial_end_date: datetime.date | None = None
    weekly_hours: Decimal | None = None
    pay_frequency: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    status: str | None = None
    end_reason: str | None = None
    components: list[ComponentBody] | None = None


class ContractAmend(BaseModel):
    effective_date: datetime.date
    contract_type: str | None = None
    end_date: datetime.date | None = None
    weekly_hours: Decimal | None = None
    base_salary: Decimal | None = None
    pay_frequency: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    components: list[ComponentBody] | None = None


class ContractEnd(BaseModel):
    end_date: datetime.date
    end_reason: str
