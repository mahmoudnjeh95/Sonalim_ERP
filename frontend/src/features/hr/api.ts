import { apiFetch } from "../../lib/api";

// ---------------------------------------------------------------------------
// Query keys: every hr read lives under ["hr", ...], so one prefix refreshes a
// file and all its tabs.
// ---------------------------------------------------------------------------
export const hrKeys = {
  employees: ["hr", "employees"] as const,
  employee: (id: string) => ["hr", "employees", id] as const,
  dependants: (id: string) => ["hr", "employees", id, "dependants"] as const,
  paymentSets: (id: string) => ["hr", "employees", id, "payment-methods"] as const,
  documents: (id: string) => ["hr", "employees", id, "documents"] as const,
  contracts: ["hr", "contracts"] as const,
  employeeContracts: (id: string) => ["hr", "contracts", id] as const,
  departments: ["hr", "departments"] as const,
  positions: ["hr", "positions"] as const,
  grades: ["hr", "grades"] as const,
  settings: ["hr", "settings"] as const,
  alerts: ["hr", "alerts"] as const,
  leave: ["hr", "leave"] as const,
  dashboard: ["hr", "dashboard"] as const,
};

// ---------------------------------------------------------------------------
// Closed lists (mirrors of backend/modules/hr/domain/*.py)
// ---------------------------------------------------------------------------
export const EMPLOYEE_STATUSES = ["active", "on_leave", "inactive", "terminated"] as const;
export type EmployeeStatus = (typeof EMPLOYEE_STATUSES)[number];
export const GENDERS = ["male", "female"] as const;
export type Gender = (typeof GENDERS)[number];
export const MARITAL_STATUSES = ["single", "married", "divorced", "widowed"] as const;
export type MaritalStatus = (typeof MARITAL_STATUSES)[number];
export const END_REASONS = [
  "term_reached",
  "resignation",
  "dismissal",
  "trial_termination",
  "mutual_agreement",
  "retirement",
  "death",
  "amended",
  "other",
] as const;
export type EndReason = (typeof END_REASONS)[number];
export type TerminationReason = Exclude<EndReason, "amended">;
export const TERMINATION_REASONS: TerminationReason[] = [
  "term_reached",
  "resignation",
  "dismissal",
  "trial_termination",
  "mutual_agreement",
  "retirement",
  "death",
  "other",
];
export const CONTRACT_TYPES = ["cdi", "cdd", "apprentice", "daily", "intern"] as const;
export type ContractType = (typeof CONTRACT_TYPES)[number];
export const CONTRACT_STATUSES = ["draft", "active", "expired", "terminated"] as const;
export type ContractStatus = (typeof CONTRACT_STATUSES)[number];
export const PAY_FREQUENCIES = ["monthly", "daily"] as const;
export type PayFrequency = (typeof PAY_FREQUENCIES)[number];
export const PAYMENT_METHODS = ["bank", "mobile_money", "cash"] as const;
export type PaymentMethodKind = (typeof PAYMENT_METHODS)[number];
export const MOBILE_OPERATORS = ["orange_money", "moov_money"] as const;
export type MobileOperator = (typeof MOBILE_OPERATORS)[number];
export const DEPENDANT_KINDS = ["spouse", "child"] as const;
export type DependantKind = (typeof DEPENDANT_KINDS)[number];
export const DOCUMENT_KINDS = [
  "id_card",
  "passport",
  "work_permit",
  "medical_certificate",
  "driving_licence",
  "diploma",
  "criminal_record",
  "signed_contract",
  "other",
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];
export type DocumentState = "expired" | "expiring" | "valid";

// ---------------------------------------------------------------------------
// Employee file
// ---------------------------------------------------------------------------
export interface EmployeeListItem {
  id: string;
  employee_no: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  department_id: string | null;
  department_name: string | null;
  job_title: string | null;
  hire_date: string;
  status: EmployeeStatus;
  position_id: string | null;
  position_title: string | null;
  grade_id: string | null;
  grade_code: string | null;
  site: string | null;
  badge_no: string | null;
  user_id: string | null;
  termination_date: string | null;
  contract_type: ContractType | null;
  contract_end_date: string | null;
}
/** Kept for the legacy leave / attendance screens. */
export type Employee = EmployeeListItem;

export interface EmployeeInput {
  employee_no: string;
  first_name: string;
  last_name: string;
  hire_date: string;
  status: EmployeeStatus;
  email?: string | null;
  phone?: string | null;
  department_id?: string | null;
  job_title?: string | null;
  user_id?: string | null;
  gender?: Gender | null;
  birth_date?: string | null;
  birth_place?: string | null;
  nationality?: string | null;
  national_id?: string | null;
  inps_no?: string | null;
  amo_no?: string | null;
  marital_status?: MaritalStatus | null;
  address?: string | null;
  emergency_contact?: string | null;
  badge_no?: string | null;
  position_id?: string | null;
  grade_id?: string | null;
  site?: string | null;
}
export type EmployeeChanges = Partial<Omit<EmployeeInput, "employee_no">>;

export interface EmployeeRecord extends Required<EmployeeInput> {
  id: string;
  full_name: string;
  department_name: string | null;
  position_title: string | null;
  grade_code: string | null;
  user_email: string | null;
  termination_date: string | null;
  termination_reason: TerminationReason | null;
  /** True when the caller lacks hr.view_sensitive: national_id, inps_no, amo_no came back null. */
  sensitive_hidden: boolean;
}

export function listEmployees(token: string) {
  return apiFetch<EmployeeListItem[]>("/hr/employees", { token });
}
export function getEmployee(token: string, id: string) {
  return apiFetch<EmployeeRecord>(`/hr/employees/${id}`, { token });
}
export function createEmployee(token: string, input: EmployeeInput) {
  return apiFetch<EmployeeRecord>("/hr/employees", { method: "POST", token, body: input });
}
export function updateEmployee(token: string, id: string, changes: EmployeeChanges) {
  return apiFetch<EmployeeRecord>(`/hr/employees/${id}`, { method: "PATCH", token, body: changes });
}
export function terminateEmployee(token: string, id: string, input: { termination_date: string; termination_reason: TerminationReason }) {
  return apiFetch<EmployeeRecord>(`/hr/employees/${id}/terminate`, { method: "POST", token, body: input });
}

// ---- family ----
export interface Dependant {
  id: string;
  employee_id: string;
  kind: DependantKind;
  name: string;
  valid_from: string;
  birth_date: string | null;
  dependent_for_tax: boolean;
  valid_to: string | null;
  counts_for_tax_today: boolean;
}
export type DependantInput = Omit<Dependant, "id" | "employee_id" | "counts_for_tax_today">;
export function listDependants(token: string, employeeId: string) {
  return apiFetch<Dependant[]>(`/hr/employees/${employeeId}/dependants`, { token });
}
export function createDependant(token: string, employeeId: string, input: DependantInput) {
  return apiFetch<Dependant>(`/hr/employees/${employeeId}/dependants`, { method: "POST", token, body: input });
}
export function updateDependant(token: string, id: string, changes: Partial<DependantInput>) {
  return apiFetch<Dependant>(`/hr/dependants/${id}`, { method: "PATCH", token, body: changes });
}

// ---- payment ----
export interface PaymentMethod {
  id: string;
  method: PaymentMethodKind;
  bank_name: string | null;
  account_no: string | null;
  mobile_operator: MobileOperator | null;
  mobile_number: string | null;
  share_percent: number;
  is_primary: boolean;
  sensitive_hidden: boolean;
}
export interface PaymentSet {
  valid_from: string;
  in_force: boolean;
  methods: PaymentMethod[];
}
export type PaymentMethodInput = Omit<PaymentMethod, "id" | "sensitive_hidden">;
export function listPaymentSets(token: string, employeeId: string) {
  return apiFetch<PaymentSet[]>(`/hr/employees/${employeeId}/payment-methods`, { token });
}
export function replacePaymentSet(token: string, employeeId: string, input: { valid_from: string; methods: PaymentMethodInput[] }) {
  return apiFetch<PaymentSet[]>(`/hr/employees/${employeeId}/payment-methods`, { method: "PUT", token, body: input });
}

// ---- contracts ----
export interface ContractComponent {
  component_code: string;
  amount: number | null;
  rate: number | null;
}
export interface Contract {
  id: string;
  employee_id: string;
  employee_name: string;
  contract_type: ContractType;
  start_date: string;
  base_salary: number | null;
  end_date: string | null;
  trial_end_date: string | null;
  weekly_hours: number;
  pay_frequency: PayFrequency;
  position_id: string | null;
  position_title: string | null;
  grade_id: string | null;
  grade_code: string | null;
  status: ContractStatus;
  amends_contract_id: string | null;
  end_reason: EndReason | null;
  currency: string;
  components: ContractComponent[];
  sensitive_hidden: boolean;
}
export interface ContractInput {
  employee_id: string;
  contract_type: ContractType;
  start_date: string;
  base_salary: number;
  end_date?: string | null;
  trial_end_date?: string | null;
  weekly_hours?: number;
  pay_frequency?: PayFrequency;
  position_id?: string | null;
  grade_id?: string | null;
  status?: "draft" | "active";
  components?: ContractComponent[];
}
export type ContractChanges = Partial<Omit<ContractInput, "employee_id">>;
export function listContracts(token: string, employeeId: string) {
  return apiFetch<Contract[]>(`/hr/contracts?employee_id=${encodeURIComponent(employeeId)}`, { token });
}
export function createContract(token: string, input: ContractInput) {
  return apiFetch<Contract>("/hr/contracts", { method: "POST", token, body: input });
}
export function updateContract(token: string, id: string, changes: ContractChanges) {
  return apiFetch<Contract>(`/hr/contracts/${id}`, { method: "PATCH", token, body: changes });
}
export function activateContract(token: string, id: string) {
  return apiFetch<Contract>(`/hr/contracts/${id}/activate`, { method: "POST", token });
}
export function endContract(token: string, id: string, input: { end_date: string; end_reason: EndReason }) {
  return apiFetch<Contract>(`/hr/contracts/${id}/end`, { method: "POST", token, body: input });
}
export function amendContract(token: string, id: string, input: ContractChanges & { effective_date: string }) {
  return apiFetch<Contract>(`/hr/contracts/${id}/amend`, { method: "POST", token, body: input });
}

// ---- documents ----
export interface EmployeeDocument {
  id: string;
  employee_id: string;
  kind: DocumentKind;
  title: string | null;
  file_ref: string | null;
  issued_on: string | null;
  expires_on: string | null;
  state: DocumentState | null;
}
export type DocumentInput = Omit<EmployeeDocument, "id" | "employee_id" | "state">;
export function listDocuments(token: string, employeeId: string) {
  return apiFetch<EmployeeDocument[]>(`/hr/employees/${employeeId}/documents`, { token });
}
export function createDocument(token: string, employeeId: string, input: DocumentInput) {
  return apiFetch<EmployeeDocument>(`/hr/employees/${employeeId}/documents`, { method: "POST", token, body: input });
}
export function updateDocument(token: string, id: string, changes: Partial<DocumentInput>) {
  return apiFetch<EmployeeDocument>(`/hr/documents/${id}`, { method: "PATCH", token, body: changes });
}

// ---- organisation ----
export interface Department {
  id: string;
  code: string;
  name: string;
  manager_employee_id: string | null;
  manager_name: string | null;
  employee_count: number;
}
export type DepartmentInput = { code: string; name: string; manager_employee_id: string | null };
export function listDepartments(token: string) {
  return apiFetch<Department[]>("/hr/departments", { token });
}
export function createDepartment(token: string, input: DepartmentInput) {
  return apiFetch<Department>("/hr/departments", { method: "POST", token, body: input });
}
export function updateDepartment(token: string, id: string, changes: Partial<DepartmentInput>) {
  return apiFetch<Department>(`/hr/departments/${id}`, { method: "PATCH", token, body: changes });
}

export interface Position {
  id: string;
  code: string;
  title: string;
  department_id: string | null;
  department_name: string | null;
  headcount_budget: number | null;
  headcount: number;
}
export type PositionInput = { code: string; title: string; department_id: string | null; headcount_budget: number | null };
export function listPositions(token: string) {
  return apiFetch<Position[]>("/hr/positions", { token });
}
export function createPosition(token: string, input: PositionInput) {
  return apiFetch<Position>("/hr/positions", { method: "POST", token, body: input });
}
export function updatePosition(token: string, id: string, changes: Partial<PositionInput>) {
  return apiFetch<Position>(`/hr/positions/${id}`, { method: "PATCH", token, body: changes });
}

export interface Grade {
  id: string;
  code: string;
  category: string;
  echelon: string;
  base_salary: number;
  valid_from: string;
}
export type GradeInput = Omit<Grade, "id">;
export function listGrades(token: string) {
  return apiFetch<Grade[]>("/hr/grades", { token });
}
export function createGrade(token: string, input: GradeInput) {
  return apiFetch<Grade>("/hr/grades", { method: "POST", token, body: input });
}
export function updateGrade(token: string, id: string, changes: Partial<GradeInput>) {
  return apiFetch<Grade>(`/hr/grades/${id}`, { method: "PATCH", token, body: changes });
}

// ---- settings and alerts ----
export interface HrSettings {
  contract_expiry_horizon_days: number | null;
  trial_end_horizon_days: number | null;
  document_expiry_horizon_days: number | null;
}
export function getHrSettings(token: string) {
  return apiFetch<HrSettings>("/hr/settings", { token });
}
export function saveHrSettings(token: string, input: HrSettings) {
  return apiFetch<HrSettings>("/hr/settings", { method: "PUT", token, body: input });
}

export interface ContractAlert {
  contract_id: string;
  employee_id: string;
  employee_no: string;
  employee_name: string;
  contract_type: ContractType;
  date: string;
}
export interface DocumentAlert {
  document_id: string;
  employee_id: string;
  employee_no: string;
  employee_name: string;
  kind: DocumentKind;
  title: string | null;
  expires_on: string;
  state: DocumentState;
}
export interface ExpiryAlerts extends HrSettings {
  as_of: string;
  contracts_ending: ContractAlert[];
  trials_ending: ContractAlert[];
  documents_expiring: DocumentAlert[];
}
export function getExpiryAlerts(token: string) {
  return apiFetch<ExpiryAlerts>("/hr/alerts/expiries", { token });
}

// ---------------------------------------------------------------------------
// Legacy screens (leave, attendance, payroll) until phases 2 and 3 replace them
// ---------------------------------------------------------------------------
export interface LeaveRequest { id: string; employee_id: string; employee_name: string; leave_type: string; start_date: string; end_date: string; reason: string | null; status: "pending" | "approved" | "rejected" | "cancelled"; reviewed_by: string | null; }
export interface Attendance { id: string; employee_id: string; employee_name: string; attendance_date: string; status: string; hours_worked: number; note: string | null; }
export interface PayrollRun { id: string; period_month: string; status: string; }
export interface Payslip { id: string; payroll_run_id: string; period_month: string; employee_name: string; base_salary: number; bonuses: number; deductions: number; taxes: number; net_salary: number; currency: string; status: string; }
export function listLeaveRequests(token: string) { return apiFetch<LeaveRequest[]>("/hr/leave-requests", { token }); }
export function getHrDashboard(token: string) { return apiFetch<{ employee_count: number; active_employee_count: number; department_count: number; pending_leave_count: number; on_leave_count: number }>("/hr/dashboard", { token }); }
export function createLeaveRequest(token: string, input: { employee_id: string; leave_type: string; start_date: string; end_date: string; reason?: string }) { return apiFetch<LeaveRequest>("/hr/leave-requests", { method: "POST", token, body: input }); }
export function reviewLeaveRequest(token: string, id: string, status: "approved" | "rejected") { return apiFetch<LeaveRequest>(`/hr/leave-requests/${id}/review`, { method: "POST", token, body: { status } }); }
export function listAttendance(token: string) { return apiFetch<Attendance[]>("/hr/attendance", { token }); }
export function listPayrollRuns(token: string) { return apiFetch<PayrollRun[]>("/hr/payroll-runs", { token }); }
export function listPayslips(token: string, runId?: string) { return apiFetch<Payslip[]>(`/hr/payslips${runId ? `?run_id=${runId}` : ""}`, { token }); }
export function createPayrollRun(token: string, input: { period_month: string; bonuses: number; deductions: number; taxes: number }) { return apiFetch<PayrollRun>("/hr/payroll-runs", { method: "POST", token, body: input }); }
export function recordAttendance(token: string, input: { employee_id: string; attendance_date: string; status: string; hours_worked: number; note?: string }) { return apiFetch<Attendance>("/hr/attendance", { method: "POST", token, body: input }); }
export interface UpdatedPayslip { id: string; base_salary: number; bonuses: number; deductions: number; taxes: number; net_salary: number; currency: string; }
export function updatePayslip(token: string, payslipId: string, input: { bonuses?: number; deductions?: number; taxes?: number }) { return apiFetch<UpdatedPayslip>(`/hr/payslips/${payslipId}`, { method: "PATCH", token, body: input }); }
