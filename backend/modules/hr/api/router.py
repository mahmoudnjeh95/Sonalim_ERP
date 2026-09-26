from __future__ import annotations

import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.hr.api.service import DepartmentService, EmployeeService, LeaveService
from modules.hr.api.contract_service import ContractService
from modules.hr.api.payroll_service import AttendanceService, PayrollService
from modules.hr.api.organisation_service import GradeService, PositionService
from modules.hr.api.access import can_view_sensitive, require, require_sensitive_for
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.schemas import (
    DependantCreate,
    DependantPatch,
    DepartmentCreate,
    DepartmentPatch,
    EmployeeCreate,
    EmployeePatch,
    GradeCreate,
    GradePatch,
    PaymentSetBody,
    PositionCreate,
    PositionPatch,
)
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod
from modules.hr.domain.sensitive import EMPLOYEE_FIELDS, PAYMENT_FIELDS, filled, mask, written

router = APIRouter(prefix="/hr", tags=["hr"])

class LeaveBody(BaseModel):
    employee_id: str
    leave_type: str
    start_date: datetime.date
    end_date: datetime.date
    reason: str | None = None

class LeaveReviewBody(BaseModel):
    status: str

class ContractBody(BaseModel):
    employee_id: str
    contract_type: str
    start_date: datetime.date
    end_date: datetime.date | None = None
    salary: float = 0
    currency: str = "USD"
    status: str = "active"

class AttendanceBody(BaseModel):
    employee_id: str
    attendance_date: datetime.date
    status: str
    hours_worked: float = 0
    note: str | None = None

class PayrollBody(BaseModel):
    period_month: datetime.date
    bonuses: float = 0
    deductions: float = 0
    taxes: float = 0

class PayslipUpdateBody(BaseModel):
    bonuses: float | None = None
    deductions: float | None = None
    taxes: float | None = None

# Refusals answered 404 / 409; every other refusal is a 422. Later phases add their codes here.
_NOT_FOUND_CODES = {"NOT_FOUND"}
_CONFLICT_CODES = {
    "BADGE_TAKEN",
    "USER_ALREADY_LINKED",
    "CONTRACT_OVERLAP",
    "ALREADY_TERMINATED",
    "EMPLOYEE_TERMINATED",
    "CONTRACT_AFTER_TERMINATION",
    "INVALID_TRANSITION",
}


def fail(result: Err) -> NoReturn:
    if result.code in _NOT_FOUND_CODES:
        code = status.HTTP_404_NOT_FOUND
    elif result.code in _CONFLICT_CODES or result.code.startswith("DUPLICATE"):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(code, err_detail(result))


def respond(connection, result):
    """Commit a successful write and return its value; roll back and raise on a refusal."""
    if isinstance(result, Err):
        connection.rollback()
        fail(result)
    connection.commit()
    return result.value

@router.get("/leave-requests")
def leave_requests(status_filter: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_leave"))):
    with get_connection() as connection: return LeaveService(connection).list_requests(tenant.tenant_id, status_filter)

@router.post("/leave-requests", status_code=status.HTTP_201_CREATED)
def create_leave(body: LeaveBody, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    with get_connection() as connection:
        result = LeaveService(connection).create_request(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        if isinstance(result, Err): connection.rollback(); fail(result)
        connection.commit(); return result.value

@router.post("/leave-requests/{request_id}/review")
def review_leave(request_id: str, body: LeaveReviewBody, tenant: TenantContext = Depends(require_permission("hr.manage_leave"))):
    with get_connection() as connection:
        result = LeaveService(connection).review_request(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, request_id=request_id, status=body.status)
        if isinstance(result, Err): connection.rollback(); fail(result)
        connection.commit(); return result.value

@router.get("/contracts")
def contracts(employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_contracts"))):
    with get_connection() as connection: return ContractService(connection).list_contracts(tenant.tenant_id, employee_id)

@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def create_contract(body: ContractBody, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    with get_connection() as connection:
        result = ContractService(connection).create_contract(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        if isinstance(result, Err): connection.rollback(); fail(result)
        connection.commit(); return result.value

@router.get("/dashboard")
def dashboard(tenant: TenantContext = Depends(require_permission("hr.view_dashboard"))):
    with get_connection() as connection:
        employees = EmployeeService(connection).list_employees(tenant.tenant_id)
        leave = LeaveService(connection).list_requests(tenant.tenant_id)
        departments = DepartmentService(connection).list_departments(tenant.tenant_id)
    return {"employee_count": len(employees), "active_employee_count": sum(e["status"] == "active" for e in employees), "department_count": len(departments), "pending_leave_count": sum(item["status"] == "pending" for item in leave), "on_leave_count": sum(e["status"] == "on_leave" for e in employees)}

@router.get("/attendance")
def attendance(tenant: TenantContext = Depends(require_permission("hr.view_attendance"))):
    with get_connection() as connection: return AttendanceService(connection).list_records(tenant_id=tenant.tenant_id)

@router.post("/attendance", status_code=status.HTTP_201_CREATED)
def record_attendance(body: AttendanceBody, tenant: TenantContext = Depends(require_permission("hr.manage_attendance"))):
    with get_connection() as connection:
        result = AttendanceService(connection).record(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        if isinstance(result, Err): connection.rollback(); fail(result)
        connection.commit(); return result.value

@router.get("/payroll-runs")
def payroll_runs(tenant: TenantContext = Depends(require_permission("hr.view_payroll"))):
    with get_connection() as connection: return PayrollService(connection).list_runs(tenant.tenant_id)

@router.post("/payroll-runs", status_code=status.HTTP_201_CREATED)
def create_payroll_run(body: PayrollBody, tenant: TenantContext = Depends(require_permission("hr.manage_payroll"))):
    with get_connection() as connection:
        result = PayrollService(connection).create_run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        if isinstance(result, Err): connection.rollback(); fail(result)
        connection.commit(); return result.value

@router.get("/payslips")
def payslips(run_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_payroll"))):
    with get_connection() as connection: return PayrollService(connection).get_payslips(tenant_id=tenant.tenant_id, run_id=run_id)

@router.patch("/payslips/{payslip_id}")
def update_payslip(payslip_id: str, body: PayslipUpdateBody, tenant: TenantContext = Depends(require_permission("hr.admin_payroll"))):
    with get_connection() as connection:
        result = PayrollService(connection).update_payslip(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, payslip_id=payslip_id, **body.model_dump())
        if isinstance(result, Err): connection.rollback(); fail(result)
        connection.commit(); return result.value

# ---- organisation: departments, positions, grades -------------------------------------------


@router.get("/departments")
def list_departments(tenant: TenantContext = Depends(require_permission("hr.view_departments"))):
    with get_connection() as connection:
        return DepartmentService(connection).list_departments(tenant.tenant_id)


@router.post("/departments", status_code=status.HTTP_201_CREATED)
def create_department(body: DepartmentCreate, tenant: TenantContext = Depends(require_permission("hr.manage_departments"))):
    with get_connection() as connection:
        result = DepartmentService(connection).create_department(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.patch("/departments/{department_id}")
def update_department(department_id: str, body: DepartmentPatch, tenant: TenantContext = Depends(require_permission("hr.admin_departments"))):
    with get_connection() as connection:
        result = DepartmentService(connection).update_department(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, department_id=department_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/positions")
def list_positions(tenant: TenantContext = Depends(require_permission("hr.view_positions"))):
    with get_connection() as connection:
        return PositionService(connection).list_positions(tenant.tenant_id)


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def create_position(body: PositionCreate, tenant: TenantContext = Depends(require_permission("hr.manage_positions"))):
    with get_connection() as connection:
        result = PositionService(connection).create_position(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.patch("/positions/{position_id}")
def update_position(position_id: str, body: PositionPatch, tenant: TenantContext = Depends(require_permission("hr.admin_positions"))):
    with get_connection() as connection:
        result = PositionService(connection).update_position(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, position_id=position_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/grades")
def list_grades(tenant: TenantContext = Depends(require_permission("hr.view_positions"))):
    with get_connection() as connection:
        return GradeService(connection).list_grades(tenant.tenant_id)


@router.post("/grades", status_code=status.HTTP_201_CREATED)
def create_grade(body: GradeCreate, tenant: TenantContext = Depends(require_permission("hr.manage_positions"))):
    with get_connection() as connection:
        result = GradeService(connection).create_grade(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.patch("/grades/{grade_id}")
def update_grade(grade_id: str, body: GradePatch, tenant: TenantContext = Depends(require_permission("hr.admin_positions"))):
    with get_connection() as connection:
        result = GradeService(connection).update_grade(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, grade_id=grade_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


# ---- the employee file ------------------------------------------------------------------------

_EMPLOYEE_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")


@router.get("/employees")
def list_employees(status_filter: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return EmployeeService(connection).list_employees(tenant.tenant_id, status_filter)


@router.get("/employees/{employee_id}")
def get_employee(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        record = EmployeeService(connection).get_employee(tenant_id=tenant.tenant_id, employee_id=employee_id)
        if record is None:
            fail(_EMPLOYEE_NOT_FOUND)
        return mask(record, EMPLOYEE_FIELDS, visible=can_view_sensitive(connection, tenant))


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(body: EmployeeCreate, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    data = body.model_dump()
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, filled(data, EMPLOYEE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = EmployeeService(connection).create_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee=EmployeeFile(**data)
        )
        return mask(respond(connection, result), EMPLOYEE_FIELDS, visible=visible)


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: str, body: EmployeePatch, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    changes = body.model_dump(exclude_unset=True)
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, written(changes, EMPLOYEE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = EmployeeService(connection).update_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, changes=changes
        )
        return mask(respond(connection, result), EMPLOYEE_FIELDS, visible=visible)


# ---- family and payment -----------------------------------------------------------------------


def _masked_sets(sets: list[dict], visible: bool) -> list[dict]:
    return [{**entry, "methods": [mask(method, PAYMENT_FIELDS, visible=visible) for method in entry["methods"]]} for entry in sets]


@router.get("/employees/{employee_id}/dependants")
def list_dependants(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return DependantService(connection).list_dependants(tenant_id=tenant.tenant_id, employee_id=employee_id)


@router.post("/employees/{employee_id}/dependants", status_code=status.HTTP_201_CREATED)
def create_dependant(employee_id: str, body: DependantCreate, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    with get_connection() as connection:
        result = DependantService(connection).create_dependant(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, dependant=Dependant(**body.model_dump())
        )
        return respond(connection, result)


@router.patch("/dependants/{dependant_id}")
def update_dependant(dependant_id: str, body: DependantPatch, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    with get_connection() as connection:
        result = DependantService(connection).update_dependant(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, dependant_id=dependant_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/employees/{employee_id}/payment-methods")
def list_payment_methods(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        sets = PaymentMethodService(connection).list_sets(tenant_id=tenant.tenant_id, employee_id=employee_id)
        return _masked_sets(sets, can_view_sensitive(connection, tenant))


@router.put("/employees/{employee_id}/payment-methods")
def replace_payment_methods(employee_id: str, body: PaymentSetBody, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    """A new start date is a creation (hr.manage_employees); replacing or removing an existing
    arrangement is an edit (hr.admin_employees). Account and phone numbers need hr.view_sensitive."""
    methods = [method.model_dump() for method in body.methods]
    with get_connection() as connection:
        service = PaymentMethodService(connection)
        if service.set_exists(tenant_id=tenant.tenant_id, employee_id=employee_id, valid_from=body.valid_from):
            require(connection, tenant, "hr.admin_employees")
        require_sensitive_for(connection, tenant, [name for method in methods for name in filled(method, PAYMENT_FIELDS)])
        visible = can_view_sensitive(connection, tenant)
        result = service.replace_set(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            employee_id=employee_id,
            valid_from=body.valid_from,
            methods=[PaymentMethod(**method) for method in methods],
        )
        return _masked_sets(respond(connection, result), visible)
