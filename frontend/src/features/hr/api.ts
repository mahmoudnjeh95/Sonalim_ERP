import { apiFetch } from "../../lib/api";

export interface Employee { id: string; employee_no: string; first_name: string; last_name: string; email: string | null; phone: string | null; department_id: string | null; department_name?: string | null; job_title: string | null; hire_date: string; status: "active" | "on_leave" | "inactive"; }
export interface Department { id: string; code: string; name: string; employee_count: number; manager_employee_id: string | null; }
export interface LeaveRequest { id: string; employee_id: string; employee_name: string; leave_type: string; start_date: string; end_date: string; reason: string | null; status: "pending" | "approved" | "rejected" | "cancelled"; reviewed_by: string | null; }
export interface Contract { id: string; employee_id: string; employee_name: string; contract_type: string; start_date: string; end_date: string | null; salary: number; currency: string; status: string; }
export interface Attendance { id: string; employee_id: string; employee_name: string; attendance_date: string; status: string; hours_worked: number; note: string | null; }
export interface PayrollRun { id: string; period_month: string; status: string; }
export interface Payslip { id: string; payroll_run_id: string; period_month: string; employee_name: string; base_salary: number; bonuses: number; deductions: number; taxes: number; net_salary: number; currency: string; status: string; }

export function listEmployees(token: string) { return apiFetch<Employee[]>("/hr/employees", { token }); }
export function listDepartments(token: string) { return apiFetch<Department[]>("/hr/departments", { token }); }
export function listLeaveRequests(token: string) { return apiFetch<LeaveRequest[]>("/hr/leave-requests", { token }); }
export function listContracts(token: string) { return apiFetch<Contract[]>("/hr/contracts", { token }); }
export function getHrDashboard(token: string) { return apiFetch<{ employee_count: number; active_employee_count: number; department_count: number; pending_leave_count: number; on_leave_count: number }>("/hr/dashboard", { token }); }
export function createDepartment(token: string, input: { code: string; name: string }) { return apiFetch<Department>("/hr/departments", { method: "POST", token, body: input }); }
export function createEmployee(token: string, input: Omit<Employee, "id" | "department_name">) { return apiFetch<Employee>("/hr/employees", { method: "POST", token, body: input }); }
export function createLeaveRequest(token: string, input: { employee_id: string; leave_type: string; start_date: string; end_date: string; reason?: string }) { return apiFetch<LeaveRequest>("/hr/leave-requests", { method: "POST", token, body: input }); }
export function reviewLeaveRequest(token: string, id: string, status: "approved" | "rejected") { return apiFetch<LeaveRequest>(`/hr/leave-requests/${id}/review`, { method: "POST", token, body: { status } }); }
export function createContract(token: string, input: { employee_id: string; contract_type: string; start_date: string; end_date?: string; salary: number; currency: string }) { return apiFetch<Contract>("/hr/contracts", { method: "POST", token, body: input }); }
export function listAttendance(token: string) { return apiFetch<Attendance[]>("/hr/attendance", { token }); }
export function listPayrollRuns(token: string) { return apiFetch<PayrollRun[]>("/hr/payroll-runs", { token }); }
export function listPayslips(token: string, runId?: string) { return apiFetch<Payslip[]>(`/hr/payslips${runId ? `?run_id=${runId}` : ""}`, { token }); }
export function createPayrollRun(token: string, input: { period_month: string; bonuses: number; deductions: number; taxes: number }) { return apiFetch<PayrollRun>("/hr/payroll-runs", { method: "POST", token, body: input }); }
export function recordAttendance(token: string, input: { employee_id: string; attendance_date: string; status: string; hours_worked: number; note?: string }) { return apiFetch<Attendance>("/hr/attendance", { method: "POST", token, body: input }); }
