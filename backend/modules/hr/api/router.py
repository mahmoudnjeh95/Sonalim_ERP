from __future__ import annotations

import datetime
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, require_session
from modules.hr.api.service import DepartmentService, EmployeeService, LeaveService
from modules.hr.api.contract_service import ContractService
from modules.hr.api.payroll_service import AttendanceService, PayrollService
from modules.hr.api.organisation_service import GradeService, PositionService
from modules.hr.api.access import can_view_sensitive, require, require_sensitive_for
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.alert_service import HrAlertService
from modules.hr.api.document_service import DocumentService
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.api.schemas import (
    ContractAmend,
    ContractCreate,
    ContractEnd,
    ContractPatch,
    DependantCreate,
    DependantPatch,
    DepartmentCreate,
    DepartmentPatch,
    DocumentCreate,
    DocumentPatch,
    EmployeeCreate,
    EmployeePatch,
    GradeCreate,
    GradePatch,
    PaymentSetBody,
    PositionCreate,
    PositionPatch,
    SettingsBody,
    TerminationBody,
)
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.document import EmployeeDocument
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod
from modules.hr.domain.sensitive import CONTRACT_WRITE_FIELDS, EMPLOYEE_FIELDS, PAYMENT_FIELDS, filled, mask, mask_contract, written

router = APIRouter(prefix="/hr", tags=["hr"])

class LeaveBody(BaseModel):
    employee_id: str
    leave_type: str
    start_date: datetime.date
    end_date: datetime.date
    reason: str | None = None

class LeaveReviewBody(BaseModel):
    status: str

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
_NOT_FOUND_CODES = {"NOT_FOUND", "NO_EMPLOYEE_FILE"}
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


@router.get("/me/profile")
def get_my_profile(tenant: TenantContext = Depends(require_session)):
    """The signed-in person's own employee file.

    No hr.view_employees here on purpose: reading your own file is not the privilege that
    reading a colleague's is. It is unmasked for the same reason get_by_user is -- the
    national, INPS and AMO numbers on it are the caller's own, already on their payslip.
    """
    with get_connection() as connection:
        record = EmployeeService(connection).get_by_user(tenant_id=tenant.tenant_id, user_id=tenant.user_id)
        if record is None:
            fail(Err("NO_EMPLOYEE_FILE", "no employee file is linked to this account",
                     "aucun dossier employé n'est lié à ce compte"))
        return record


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
    """Relinking user_id (not just setting it the first time) needs hr.view_sensitive too: once
    self-service ships, whoever holds that file's login reads its unmasked NINA/INPS/AMO and
    payslips through get_by_user. Setting it on create stays open (nothing hidden exists yet)."""
    changes = body.model_dump(exclude_unset=True)
    with get_connection() as connection:
        service = EmployeeService(connection)
        require_sensitive_for(connection, tenant, written(changes, EMPLOYEE_FIELDS))
        if "user_id" in changes:
            current = service.get_employee(tenant_id=tenant.tenant_id, employee_id=employee_id)
            if current is not None and changes["user_id"] != current["user_id"]:
                require(connection, tenant, "hr.view_sensitive")
        visible = can_view_sensitive(connection, tenant)
        result = service.update_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, changes=changes
        )
        return mask(respond(connection, result), EMPLOYEE_FIELDS, visible=visible)


@router.post("/employees/{employee_id}/terminate")
def terminate_employee(employee_id: str, body: TerminationBody, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    with get_connection() as connection:
        visible = can_view_sensitive(connection, tenant)
        result = EmployeeService(connection).terminate_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id,
            termination_date=body.termination_date, termination_reason=body.termination_reason,
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
    arrangement is an edit (hr.admin_employees). Account and phone numbers need hr.view_sensitive.
    A caller who cannot see the numbers must not be able to erase them either: replacing or
    removing a set that already carries a number needs hr.view_sensitive too, even when the new
    body carries none (an empty body removes the set)."""
    methods = [method.model_dump() for method in body.methods]
    with get_connection() as connection:
        service = PaymentMethodService(connection)
        visible = can_view_sensitive(connection, tenant)
        if service.set_exists(tenant_id=tenant.tenant_id, employee_id=employee_id, valid_from=body.valid_from):
            require(connection, tenant, "hr.admin_employees")
            if not visible and service.set_holds_numbers(tenant_id=tenant.tenant_id, employee_id=employee_id, valid_from=body.valid_from):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    {
                        "code": "FORBIDDEN",
                        "message": "this arrangement holds a bank or mobile number; missing permission: hr.view_sensitive",
                        "message_fr": "cet arrangement comporte un numéro bancaire ou mobile ; permission manquante : hr.view_sensitive",
                    },
                )
        require_sensitive_for(connection, tenant, [name for method in methods for name in filled(method, PAYMENT_FIELDS)])
        result = service.replace_set(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            employee_id=employee_id,
            valid_from=body.valid_from,
            methods=[PaymentMethod(**method) for method in methods],
        )
        return _masked_sets(respond(connection, result), visible)


# ---- contracts ------------------------------------------------------------------------------------

_CONTRACT_NOT_FOUND = Err("NOT_FOUND", "contract not found", "contrat introuvable")


def _terms_from(data: dict) -> ContractTerms:
    components = tuple(ContractComponent(**component) for component in data.pop("components"))
    return ContractTerms(**data, components=components)


@router.get("/contracts")
def list_contracts(employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_contracts"))):
    with get_connection() as connection:
        contracts = ContractService(connection).list_contracts(tenant.tenant_id, employee_id)
        visible = can_view_sensitive(connection, tenant)
        return [mask_contract(contract, visible=visible) for contract in contracts]


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: str, tenant: TenantContext = Depends(require_permission("hr.view_contracts"))):
    with get_connection() as connection:
        contract = ContractService(connection).get_contract(tenant_id=tenant.tenant_id, contract_id=contract_id)
        if contract is None:
            fail(_CONTRACT_NOT_FOUND)
        return mask_contract(contract, visible=can_view_sensitive(connection, tenant))


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def create_contract(body: ContractCreate, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    """A contract always sets pay, so creating one needs hr.view_sensitive."""
    data = body.model_dump()
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, filled(data, CONTRACT_WRITE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).create_contract(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, terms=_terms_from(data))
        return mask_contract(respond(connection, result), visible=visible)


@router.patch("/contracts/{contract_id}")
def update_contract(contract_id: str, body: ContractPatch, tenant: TenantContext = Depends(require_permission("hr.admin_contracts"))):
    changes = body.model_dump(exclude_unset=True)
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, written(changes, CONTRACT_WRITE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).update_contract(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id, changes=changes
        )
        return mask_contract(respond(connection, result), visible=visible)


@router.post("/contracts/{contract_id}/activate")
def activate_contract(contract_id: str, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    with get_connection() as connection:
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).activate_contract(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id)
        return mask_contract(respond(connection, result), visible=visible)


@router.post("/contracts/{contract_id}/end")
def end_contract(contract_id: str, body: ContractEnd, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    with get_connection() as connection:
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).end_contract(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id, end_date=body.end_date, end_reason=body.end_reason
        )
        return mask_contract(respond(connection, result), visible=visible)


@router.post("/contracts/{contract_id}/amend", status_code=status.HTTP_201_CREATED)
def amend_contract(contract_id: str, body: ContractAmend, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    changes = body.model_dump(exclude_unset=True, exclude={"effective_date"})
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, written(changes, CONTRACT_WRITE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).amend_contract(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id, effective_date=body.effective_date, changes=changes
        )
        return mask_contract(respond(connection, result), visible=visible)


# ---- documents, settings, alerts --------------------------------------------------------------


@router.get("/employees/{employee_id}/documents")
def list_documents(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return DocumentService(connection).list_documents(tenant_id=tenant.tenant_id, employee_id=employee_id)


@router.post("/employees/{employee_id}/documents", status_code=status.HTTP_201_CREATED)
def create_document(employee_id: str, body: DocumentCreate, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    with get_connection() as connection:
        result = DocumentService(connection).create_document(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, document=EmployeeDocument(**body.model_dump())
        )
        return respond(connection, result)


@router.patch("/documents/{document_id}")
def update_document(document_id: str, body: DocumentPatch, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    with get_connection() as connection:
        result = DocumentService(connection).update_document(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, document_id=document_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return HrSettingsService(connection).get(tenant.tenant_id)


@router.put("/settings")
def save_settings(body: SettingsBody, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    with get_connection() as connection:
        result = HrSettingsService(connection).save(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.get("/alerts/expiries")
def expiry_alerts(tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return HrAlertService(connection).expiry_alerts(tenant_id=tenant.tenant_id, today=datetime.date.today())
