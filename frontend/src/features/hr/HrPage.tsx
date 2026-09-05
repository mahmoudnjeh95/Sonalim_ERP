import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CalendarDays, Users } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { toast } from "sonner";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { createContract, createDepartment, createEmployee, createLeaveRequest, createPayrollRun, getHrDashboard, listAttendance, listContracts, listDepartments, listEmployees, listLeaveRequests, listPayslips, recordAttendance, reviewLeaveRequest, updatePayslip, type Employee, type LeaveRequest, type Payslip } from "./api";

const key = { employees: ["hr", "employees"], departments: ["hr", "departments"], leave: ["hr", "leave"], contracts: ["hr", "contracts"], attendance: ["hr", "attendance"], payslips: ["hr", "payslips"], dashboard: ["hr", "dashboard"] } as const;
type Tab = "employees" | "departments" | "leave" | "contracts" | "attendance" | "payroll";

export function HrPage() {
  const { session } = useAuth(); const { t } = useI18n(); const token = session!.token; const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("employees"); const [status, setStatus] = useState<"all" | Employee["status"]>("all");
  const [employee, setEmployee] = useState({ employee_no: "", first_name: "", last_name: "", job_title: "", hire_date: new Date().toISOString().slice(0, 10) });
  const [department, setDepartment] = useState({ code: "", name: "" }); const [leave, setLeave] = useState({ employee_id: "", leave_type: "annual", start_date: "", end_date: "" });
  const [contract, setContract] = useState({ employee_id: "", contract_type: "permanent", start_date: new Date().toISOString().slice(0, 10), salary: 0 });
  const [attendance, setAttendance] = useState({ employee_id: "", attendance_date: new Date().toISOString().slice(0, 10), status: "present", hours_worked: 8 });
  const [payroll, setPayroll] = useState({ period_month: `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}-01`, bonuses: 0, deductions: 0, taxes: 0 });
  const dashboard = useQuery({ queryKey: key.dashboard, queryFn: () => getHrDashboard(token) }); const employees = useQuery({ queryKey: key.employees, queryFn: () => listEmployees(token) }); const departments = useQuery({ queryKey: key.departments, queryFn: () => listDepartments(token) }); const leaves = useQuery({ queryKey: key.leave, queryFn: () => listLeaveRequests(token) }); const contracts = useQuery({ queryKey: key.contracts, queryFn: () => listContracts(token) }); const attendanceRows = useQuery({ queryKey: key.attendance, queryFn: () => listAttendance(token), enabled: tab === "attendance" }); const payslips = useQuery({ queryKey: key.payslips, queryFn: () => listPayslips(token), enabled: tab === "payroll" });
  const refresh = (keys: readonly unknown[]) => client.invalidateQueries({ queryKey: keys });
  const employeeMutation = useMutation({ mutationFn: () => createEmployee(token, { ...employee, email: null, phone: null, department_id: null, status: "active" }), onSuccess: () => { refresh(key.employees); refresh(key.dashboard); toast.success(t("hr.employee.created")); } });
  const departmentMutation = useMutation({ mutationFn: () => createDepartment(token, department), onSuccess: () => { refresh(key.departments); toast.success(t("hr.department.created")); } });
  const leaveMutation = useMutation({ mutationFn: () => createLeaveRequest(token, leave), onSuccess: () => { refresh(key.leave); refresh(key.dashboard); toast.success(t("hr.leave.created")); } });
  const contractMutation = useMutation({ mutationFn: () => createContract(token, { ...contract, end_date: undefined, currency: "USD" }), onSuccess: () => { refresh(key.contracts); toast.success(t("hr.contract.created")); } });
  const attendanceMutation = useMutation({ mutationFn: () => recordAttendance(token, attendance), onSuccess: () => { refresh(key.attendance); toast.success(t("hr.attendance.created")); } });
  const payrollMutation = useMutation({ mutationFn: () => createPayrollRun(token, payroll), onSuccess: () => { refresh(key.payslips); refresh(key.dashboard); toast.success(t("hr.payroll.created")); } });
  const visibleEmployees = (employees.data ?? []).filter((item) => status === "all" || item.status === status);
  const employeeOptions = <>{(employees.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.first_name} {item.last_name}</option>)}</>;

  return <div className="space-y-6"><Header t={t} /><Metrics data={dashboard.data} t={t} /><nav className="flex flex-wrap gap-2 border-b pb-2">{(["employees", "departments", "leave", "contracts", "attendance", "payroll"] as Tab[]).map((item) => <button key={item} className={`rounded-md px-3 py-2 text-sm ${tab === item ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`} onClick={() => setTab(item)}>{t(`hr.tab.${item}` as never)}</button>)}</nav>
    {tab === "employees" && <Card><CardHeader className="flex-row items-center justify-between"><CardTitle>{t("hr.employees.title")}</CardTitle><FilterTabs value={status} onChange={setStatus} options={[{ value: "all", label: t("common.all") }, { value: "active", label: t("hr.status.active") }, { value: "on_leave", label: t("hr.status.onLeave") }, { value: "inactive", label: t("hr.status.inactive") }]} /></CardHeader><CardContent><InlineForm><Input required placeholder={t("hr.employee.number")} value={employee.employee_no} onChange={(e) => setEmployee({ ...employee, employee_no: e.target.value })} /><Input required placeholder={t("hr.employee.firstName")} value={employee.first_name} onChange={(e) => setEmployee({ ...employee, first_name: e.target.value })} /><Input required placeholder={t("hr.employee.lastName")} value={employee.last_name} onChange={(e) => setEmployee({ ...employee, last_name: e.target.value })} /><Input placeholder={t("hr.employee.jobTitle")} value={employee.job_title} onChange={(e) => setEmployee({ ...employee, job_title: e.target.value })} /><Button onClick={() => employeeMutation.mutate()}>{t("hr.employee.new")}</Button></InlineForm><SimpleTable tableKey="hr.employees" headers={[t("hr.employee.number"), t("hr.employee.name"), t("hr.employee.jobTitle"), t("hr.employee.department"), t("hr.employee.status")]} rows={visibleEmployees.map((item) => [item.employee_no, `${item.first_name} ${item.last_name}`, item.job_title || "-", item.department_name || "-", item.status])} /></CardContent></Card>}
    {tab === "departments" && <><InlineForm><Input required placeholder={t("hr.department.code")} value={department.code} onChange={(e) => setDepartment({ ...department, code: e.target.value })} /><Input required placeholder={t("hr.department.name")} value={department.name} onChange={(e) => setDepartment({ ...department, name: e.target.value })} /><Button onClick={() => departmentMutation.mutate()}>{t("hr.department.new")}</Button></InlineForm><SimpleTable tableKey="hr.departments" headers={[t("hr.department.code"), t("hr.department.name"), t("hr.department.count")]} rows={(departments.data ?? []).map((item) => [item.code, item.name, String(item.employee_count)])} /></>}
    {tab === "leave" && <><InlineForm><Select value={leave.employee_id} onChange={(e) => setLeave({ ...leave, employee_id: e.target.value })}><option value="">{t("hr.employee.name")}</option>{employeeOptions}</Select><Input placeholder={t("hr.leave.type")} value={leave.leave_type} onChange={(e) => setLeave({ ...leave, leave_type: e.target.value })} /><Input type="date" value={leave.start_date} onChange={(e) => setLeave({ ...leave, start_date: e.target.value })} /><Input type="date" value={leave.end_date} onChange={(e) => setLeave({ ...leave, end_date: e.target.value })} /><Button disabled={!leave.employee_id} onClick={() => leaveMutation.mutate()}>{t("hr.leave.new")}</Button></InlineForm><LeaveTable requests={leaves.data ?? []} token={token} onRefresh={() => refresh(key.leave)} /></>}
    {tab === "contracts" && <><InlineForm><Select value={contract.employee_id} onChange={(e) => setContract({ ...contract, employee_id: e.target.value })}><option value="">{t("hr.employee.name")}</option>{employeeOptions}</Select><Input placeholder={t("hr.contract.type")} value={contract.contract_type} onChange={(e) => setContract({ ...contract, contract_type: e.target.value })} /><Input type="date" value={contract.start_date} onChange={(e) => setContract({ ...contract, start_date: e.target.value })} /><Input type="number" min="0" placeholder={t("hr.contract.salary")} value={contract.salary} onChange={(e) => setContract({ ...contract, salary: Number(e.target.value) })} /><Button disabled={!contract.employee_id} onClick={() => contractMutation.mutate()}>{t("hr.contract.new")}</Button></InlineForm><SimpleTable tableKey="hr.contracts" headers={[t("hr.employee.name"), t("hr.contract.type"), t("hr.contract.start"), t("hr.contract.salary"), t("hr.employee.status")]} rows={(contracts.data ?? []).map((item) => [item.employee_name, item.contract_type, item.start_date, `${item.salary} ${item.currency}`, item.status])} /></>}
    {tab === "attendance" && <><InlineForm><Select value={attendance.employee_id} onChange={(e) => setAttendance({ ...attendance, employee_id: e.target.value })}><option value="">{t("hr.employee.name")}</option>{employeeOptions}</Select><Input type="date" value={attendance.attendance_date} onChange={(e) => setAttendance({ ...attendance, attendance_date: e.target.value })} /><Input type="number" min="0" value={attendance.hours_worked} onChange={(e) => setAttendance({ ...attendance, hours_worked: Number(e.target.value) })} /><Button disabled={!attendance.employee_id} onClick={() => attendanceMutation.mutate()}>{t("hr.attendance.record")}</Button></InlineForm><SimpleTable tableKey="hr.attendance" headers={[t("hr.employee.name"), t("hr.attendance.date"), t("hr.attendance.status"), t("hr.attendance.hours")]} rows={(attendanceRows.data ?? []).map((item) => [item.employee_name, item.attendance_date, item.status, String(item.hours_worked)])} /></>}
    {tab === "payroll" && <><p className="flex items-center gap-1 text-xs text-muted-foreground">{t("hr.payroll.help")}<HelpTooltip text={t("hr.payroll.help.detail")} /></p><InlineForm><Input type="date" value={payroll.period_month} onChange={(e) => setPayroll({ ...payroll, period_month: e.target.value })} /><Input type="number" min="0" placeholder={t("hr.payroll.bonuses")} value={payroll.bonuses} onChange={(e) => setPayroll({ ...payroll, bonuses: Number(e.target.value) })} /><Input type="number" min="0" placeholder={t("hr.payroll.deductions")} value={payroll.deductions} onChange={(e) => setPayroll({ ...payroll, deductions: Number(e.target.value) })} /><Input type="number" min="0" placeholder={t("hr.payroll.taxes")} value={payroll.taxes} onChange={(e) => setPayroll({ ...payroll, taxes: Number(e.target.value) })} /><Button onClick={() => payrollMutation.mutate()}>{t("hr.payroll.calculate")}</Button></InlineForm><PayslipsTable payslips={payslips.data ?? []} token={token} onRefresh={() => refresh(key.payslips)} /></>}
  </div>;
}

function Header({ t }: { t: (key: never) => string }) { return <div><h1 className="text-xl font-semibold tracking-tight">{t("hr.title" as never)}</h1><p className="text-sm text-muted-foreground">{t("hr.subtitle" as never)}</p></div>; }
function Metrics({ data, t }: { data?: { employee_count: number; active_employee_count: number; department_count: number; pending_leave_count: number; on_leave_count: number }; t: (key: never) => string }) { const items = [[Users, data?.employee_count, "hr.stat.employees"], [Users, data?.active_employee_count, "hr.stat.active"], [Building2, data?.department_count, "hr.stat.departments"], [CalendarDays, data?.pending_leave_count, "hr.stat.pendingLeave"], [CalendarDays, data?.on_leave_count, "hr.stat.onLeave"]] as const; return <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{items.map(([Icon, value, label]) => <Card key={label}><CardContent className="flex items-center gap-3 p-4"><Icon className="h-5 w-5 text-primary" /><div><p className="text-xl font-semibold">{value ?? "-"}</p><p className="text-xs text-muted-foreground">{t(label as never)}</p></div></CardContent></Card>)}</div>; }
function InlineForm({ children }: { children: ReactNode }) { return <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border bg-muted/20 p-4">{children}</div>; }
function SimpleTable({ tableKey, headers, rows }: { tableKey: string; headers: string[]; rows: string[][] }) {
  const columns: ColumnDef<string[]>[] = headers.map((header, i) => ({
    key: String(i),
    header,
    defaultWidth: 160,
    cell: (row) => row[i],
    sortValue: (row) => row[i],
  }));
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const sortedRows = sortRows(rows);
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </div>
      <Table colWidths={colWidths}>
        <TableHeader>
          <TableRow>
            {visibleColumns.map((column) => (
              <ResizableTableHead
                key={column.key}
                width={getWidth(column.key)}
                onResize={(width) => setWidth(column.key, width)}
                sortDirection={sortDirectionFor(column.key)}
                onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
              >
                {column.header}
              </ResizableTableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedRows.map((row, ri) => (
            <TableRow key={`${row.join("-")}-${ri}`}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key}>{column.cell(row)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
function LeaveTable({ requests, token, onRefresh }: { requests: LeaveRequest[]; token: string; onRefresh: () => void }) { const { t } = useI18n(); const mutation = useMutation({ mutationFn: ({ id, status }: { id: string; status: "approved" | "rejected" }) => reviewLeaveRequest(token, id, status), onSuccess: onRefresh }); return <Card><CardHeader><CardTitle>{t("hr.leave.title")}</CardTitle></CardHeader><CardContent><SimpleTable tableKey="hr.leave" headers={[t("hr.employee.name"), t("hr.leave.type"), t("hr.leave.dates"), t("hr.employee.status")]} rows={requests.map((request) => [request.employee_name, request.leave_type, `${request.start_date} - ${request.end_date}`, request.status])} />{requests.filter((request) => request.status === "pending").map((request) => <div key={request.id} className="mt-2 flex justify-end gap-2"><Button size="sm" onClick={() => mutation.mutate({ id: request.id, status: "approved" })}>{t("hr.leave.approve")}</Button><Button size="sm" variant="outline" onClick={() => mutation.mutate({ id: request.id, status: "rejected" })}>{t("hr.leave.reject")}</Button></div>)}</CardContent></Card>; }

function PayslipsTable({ payslips, token, onRefresh }: { payslips: Payslip[]; token: string; onRefresh: () => void }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("hr.payroll.payslips.title")}
          <HelpTooltip text={t("hr.payroll.payslips.help")} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {payslips.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("hr.payroll.payslips.empty")}</p>
        ) : (
          payslips.map((payslip) => <PayslipRow key={payslip.id} payslip={payslip} token={token} onSaved={onRefresh} />)
        )}
      </CardContent>
    </Card>
  );
}

function PayslipRow({ payslip, token, onSaved }: { payslip: Payslip; token: string; onSaved: () => void }) {
  const { t } = useI18n();
  const [bonuses, setBonuses] = useState(String(payslip.bonuses));
  const [deductions, setDeductions] = useState(String(payslip.deductions));
  const [taxes, setTaxes] = useState(String(payslip.taxes));

  const mutation = useMutation({
    mutationFn: () =>
      updatePayslip(token, payslip.id, { bonuses: Number(bonuses) || 0, deductions: Number(deductions) || 0, taxes: Number(taxes) || 0 }),
    onSuccess: () => {
      onSaved();
      toast.success(t("hr.payroll.payslips.saved"));
    },
    onError: (error) => toast.error(t("hr.payroll.payslips.saveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const previewNet = payslip.base_salary + (Number(bonuses) || 0) - (Number(deductions) || 0) - (Number(taxes) || 0);
  const isDirty = Number(bonuses) !== payslip.bonuses || Number(deductions) !== payslip.deductions || Number(taxes) !== payslip.taxes;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2.5 text-sm">
      <span className="w-40 shrink-0 font-medium">{payslip.employee_name}</span>
      <span className="w-28 shrink-0 text-xs text-muted-foreground">
        {t("hr.payroll.base")}: {payslip.base_salary}
      </span>
      <Input type="number" min="0" step="any" className="h-8 w-24" placeholder={t("hr.payroll.bonuses")} value={bonuses} onChange={(e) => setBonuses(e.target.value)} />
      <Input type="number" min="0" step="any" className="h-8 w-24" placeholder={t("hr.payroll.deductions")} value={deductions} onChange={(e) => setDeductions(e.target.value)} />
      <Input type="number" min="0" step="any" className="h-8 w-24" placeholder={t("hr.payroll.taxes")} value={taxes} onChange={(e) => setTaxes(e.target.value)} />
      <span className="text-xs font-medium tabular-nums text-muted-foreground">
        {t("hr.payroll.net")}: {previewNet} {payslip.currency}
      </span>
      <Button size="sm" variant="outline" disabled={!isDirty || mutation.isPending} onClick={() => mutation.mutate()}>
        {mutation.isPending ? t("hr.payroll.payslips.saving") : t("hr.payroll.payslips.save")}
      </Button>
    </div>
  );
}
