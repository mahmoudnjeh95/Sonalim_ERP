import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Ban, Pencil, PiggyBank, Plus } from "lucide-react";
import { toast } from "sonner";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { LOAN_STATUSES, useCancelLoan, useCreateLoan, useLoans, useUpdateLoan, type Loan, type LoanInstalment, type LoanStatus } from "../api";
import { formatPeriod, formatXof, monthInputValue, parseMonthInput, periodParam } from "../format";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { PayrollTable } from "../PayrollTable";
import { EmployeeSelect } from "./EmployeeSelect";

type StatusFilter = "all" | LoanStatus;

interface Draft {
  employeeId: string;
  principal: string;
  instalmentCount: string;
  firstMonth: string;
  note: string;
}

/** INPUT_INVALID is about the values typed, so it is shown next to them; any other refusal under the form. */
function splitRefusal(error: unknown): { field: string | null; form: string | null } {
  if (!error) return { field: null, form: null };
  if (error instanceof ApiError && error.code === "INPUT_INVALID") return { field: error.message, form: null };
  return { field: null, form: error instanceof Error ? error.message : String(error) };
}

/** Where an instalment stands: taken by an approved/paid run, held by a calculated one, or still due. */
function instalmentState(item: LoanInstalment): "deducted" | "pending" | "due" {
  if (item.deducted) return "deducted";
  return item.run_status === "calculated" ? "pending" : "due";
}

const STATE_VARIANT = { deducted: "success", pending: "primary", due: "outline" } as const;

export function LoansTab() {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("payroll.manage_inputs");
  const [status, setStatus] = useState<StatusFilter>("all");
  const loans = useLoans(status === "all" ? undefined : status);
  const create = useCreateLoan();
  const update = useUpdateLoan();
  const cancel = useCancelLoan();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Loan | null>(null);
  const [cancelling, setCancelling] = useState<Loan | null>(null);
  const [scheduleId, setScheduleId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({ employeeId: "", principal: "", instalmentCount: "", firstMonth: "", note: "" });
  const filters = useColumnFilters<Loan>([
    { key: "employee", kind: "text", getValue: (row) => `${row.full_name} ${row.employee_no}` },
    { key: "principal", kind: "range", getValue: (row) => row.principal },
    { key: "remaining", kind: "range", getValue: (row) => row.remaining },
  ]);
  const dash = <span className="text-muted-foreground">—</span>;
  // Read from the list so the schedule follows a refetch.
  const schedule = (loans.data ?? []).find((loan) => loan.id === scheduleId) ?? null;

  const mutation = editing ? update : create;
  const refusal = splitRefusal(mutation.error);
  const firstPeriod = parseMonthInput(draft.firstMonth);

  const openDialog = (row: Loan | null) => {
    create.reset();
    update.reset();
    setEditing(row);
    setDraft(
      row
        ? { employeeId: row.employee_id, principal: String(row.principal), instalmentCount: String(row.instalment_count), firstMonth: monthInputValue(row.first_period), note: row.note ?? "" }
        : { employeeId: "", principal: "", instalmentCount: "", firstMonth: monthInputValue(periodParam(new Date())), note: "" },
    );
    setDialogOpen(true);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const values = { principal: Number(draft.principal), instalment_count: Number(draft.instalmentCount), first_period: firstPeriod, note: draft.note.trim() || null };
    const onSuccess = () => {
      toast.success(t(editing ? "payroll.loans.updated" : "payroll.loans.created"));
      setDialogOpen(false);
    };
    if (editing) update.mutate({ id: editing.id, changes: values }, { onSuccess });
    else create.mutate({ employee_id: draft.employeeId, ...values }, { onSuccess });
  };

  const confirmCancel = () => {
    if (!cancelling) return;
    cancel.mutate(cancelling.id, {
      onSuccess: () => {
        toast.success(t("payroll.loans.cancelled"));
        setCancelling(null);
      },
      onError: (error) => toast.error(t("payroll.loans.refused"), { description: error instanceof Error ? error.message : undefined }),
    });
  };

  // Once an approved run deducted an instalment the schedule is history: the server refuses edits
  // (RUN_LOCKED) and asks for a cancel + new loan, so only Cancel is offered.
  const actionsFor = (row: Loan): RowAction[] =>
    row.status !== "active"
      ? []
      : [
          ...(row.instalments.some((item) => item.deducted)
            ? []
            : [{ key: "edit", label: t("payroll.inputs.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => openDialog(row) }]),
          { key: "cancel", label: t("payroll.loans.cancel"), icon: <Ban className="h-3.5 w-3.5" />, tone: "destructive" as const, onSelect: () => setCancelling(row) },
        ];

  const money = (key: string, header: TranslationKey, get: (row: Loan) => number): ColumnDef<Loan> => ({
    key,
    header: t(header),
    defaultWidth: 150,
    headerClassName: "text-right",
    cellClassName: "text-right tabular-nums",
    cell: (row) => formatXof(get(row)),
    sortValue: get,
    filterCell: filters.rangeCell(key),
  });

  const columns: ColumnDef<Loan>[] = [
    {
      key: "employee",
      header: t("payroll.inputs.column.employee"),
      defaultWidth: 240,
      cell: (row) => (
        <span>
          <span className="font-medium">{row.full_name}</span>
          <span className="ml-1.5 text-xs text-muted-foreground">{row.employee_no}</span>
        </span>
      ),
      sortValue: (row) => row.full_name,
      filterCell: filters.textCell("employee", t("payroll.inputs.filter.employee")),
    },
    money("principal", "payroll.loans.column.principal", (row) => row.principal),
    {
      key: "instalments",
      header: t("payroll.loans.column.instalments"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => row.instalment_count,
      sortValue: (row) => row.instalment_count,
    },
    money("remaining", "payroll.loans.column.remaining", (row) => row.remaining),
    {
      key: "firstPeriod",
      header: t("payroll.loans.column.firstPeriod"),
      defaultWidth: 160,
      cell: (row) => <span className="capitalize">{formatPeriod(row.first_period)}</span>,
      sortValue: (row) => row.first_period,
    },
    {
      key: "status",
      header: t("payroll.advances.column.status"),
      defaultWidth: 120,
      cell: (row) => <PayrollStatusBadge domain="loan" status={row.status} />,
      sortValue: (row) => LOAN_STATUSES.indexOf(row.status),
    },
    {
      key: "note",
      header: t("payroll.inputs.column.note"),
      defaultWidth: 200,
      cell: (row) => row.note ?? dash,
    },
    ...(canWrite
      ? [
          {
            key: "actions",
            header: "",
            defaultWidth: 70,
            alwaysVisible: true,
            cellClassName: "text-right",
            cell: (row: Loan) => <RowActionsMenu actions={actionsFor(row)} />,
          },
        ]
      : []),
  ];

  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("payroll.runs.filter.all") },
    ...LOAN_STATUSES.map((value) => ({ value, label: t(`payroll.status.loan.${value}` as TranslationKey) })),
  ];

  return (
    <div className="space-y-3">
      {loans.error && <p className="text-sm text-destructive">{loans.error instanceof ApiError ? loans.error.message : t("payroll.loans.loadError")}</p>}
      <PayrollTable
        tableKey="payroll.inputs.loans"
        columns={columns}
        rows={filters.apply(loans.data ?? [])}
        rowKey={(row) => row.id}
        loading={loans.isLoading}
        emptyTitle={t("payroll.loans.empty.title")}
        emptyDescription={t("payroll.loans.empty.description")}
        emptyIcon={<PiggyBank className="h-5 w-5" />}
        toolbar={
          <>
            <FilterTabs value={status} onChange={setStatus} options={statusOptions} />
            {canWrite && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("payroll.loans.new")}
              </Button>
            )}
          </>
        }
        filtersActive={filters.isActive || status !== "all"}
        onClearFilters={() => {
          filters.reset();
          setStatus("all");
        }}
        onRowClick={(row) => setScheduleId(row.id)}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t(editing ? "payroll.loans.editTitle" : "payroll.loans.new")}</DialogTitle>
            <DialogDescription>{t("payroll.loans.dialogHint")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <Label htmlFor="loan-first-period">{t("payroll.loans.column.firstPeriod")}</Label>
              <Input
                id="loan-first-period"
                type="month"
                required
                value={draft.firstMonth}
                onChange={(event) => setDraft((current) => ({ ...current, firstMonth: event.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="loan-employee">{t("payroll.inputs.column.employee")}</Label>
              {editing ? (
                <p className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-sm">
                  <span className="font-medium">{editing.full_name}</span>
                  <span className="ml-1.5 text-xs text-muted-foreground">{editing.employee_no}</span>
                </p>
              ) : (
                <EmployeeSelect id="loan-employee" period={firstPeriod} value={draft.employeeId} onChange={(employeeId) => setDraft((current) => ({ ...current, employeeId }))} />
              )}
            </div>
            {/* Review focus 4: INPUT_INVALID stays next to the principal and instalments, not only in a toast. */}
            <div className="space-y-1.5">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="loan-principal">{t("payroll.loans.field.principal")}</Label>
                  <Input
                    id="loan-principal"
                    type="number"
                    min={1}
                    step={1}
                    required
                    value={draft.principal}
                    aria-invalid={refusal.field ? true : undefined}
                    aria-describedby={refusal.field ? "loan-error" : undefined}
                    className={refusal.field ? "border-destructive focus-visible:ring-destructive" : undefined}
                    onChange={(event) => setDraft((current) => ({ ...current, principal: event.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="loan-instalments">{t("payroll.loans.field.instalmentCount")}</Label>
                  <Input
                    id="loan-instalments"
                    type="number"
                    min={1}
                    step={1}
                    required
                    value={draft.instalmentCount}
                    aria-invalid={refusal.field ? true : undefined}
                    aria-describedby={refusal.field ? "loan-error" : undefined}
                    className={refusal.field ? "border-destructive focus-visible:ring-destructive" : undefined}
                    onChange={(event) => setDraft((current) => ({ ...current, instalmentCount: event.target.value }))}
                  />
                </div>
              </div>
              {refusal.field && (
                <p id="loan-error" role="alert" className="text-sm text-destructive">
                  {refusal.field}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="loan-note">{t("payroll.inputs.column.note")}</Label>
              <Input id="loan-note" value={draft.note} onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value }))} />
            </div>
            {refusal.form && <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">{refusal.form}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!draft.employeeId || !draft.principal || !draft.instalmentCount || !firstPeriod || mutation.isPending}>
                {mutation.isPending ? t("common.saving") : t("common.save")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={schedule !== null} onOpenChange={(open) => !open && setScheduleId(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("payroll.loans.schedule.title")}</DialogTitle>
            <DialogDescription>
              {schedule ? `${schedule.full_name} · ${formatXof(schedule.principal)} · ${t("payroll.loans.column.remaining")} ${formatXof(schedule.remaining)}` : null}
            </DialogDescription>
          </DialogHeader>
          {schedule && schedule.instalments.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("payroll.loans.schedule.empty")}</p>
          ) : (
            <div className="rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">{t("payroll.loans.schedule.column.seq")}</TableHead>
                    <TableHead>{t("payroll.common.period")}</TableHead>
                    <TableHead className="text-right">{t("payroll.common.amount")}</TableHead>
                    <TableHead>{t("payroll.loans.schedule.column.state")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(schedule?.instalments ?? []).map((item) => {
                    const state = instalmentState(item);
                    return (
                      <TableRow key={item.id}>
                        <TableCell className="tabular-nums">{item.seq}</TableCell>
                        <TableCell className="capitalize">{formatPeriod(item.period)}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatXof(item.amount)}</TableCell>
                        <TableCell>
                          {item.run_id && state !== "due" ? (
                            <Link to={`/payroll/runs/${item.run_id}`}>
                              <Badge variant={STATE_VARIANT[state]}>{t(`payroll.loans.schedule.state.${state}` as TranslationKey)}</Badge>
                            </Link>
                          ) : (
                            <Badge variant={STATE_VARIANT[state]}>{t(`payroll.loans.schedule.state.${state}` as TranslationKey)}</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={cancelling !== null} onOpenChange={(open) => !open && setCancelling(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.loans.cancelDialog.title")}</DialogTitle>
            <DialogDescription>{cancelling ? `${cancelling.full_name} · ${formatXof(cancelling.principal)}` : null}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("payroll.loans.cancelDialog.body")}</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCancelling(null)}>
              {t("payroll.inputs.keep")}
            </Button>
            <Button variant="destructive" onClick={confirmCancel} disabled={cancel.isPending}>
              <Ban className="h-4 w-4" />
              {t("payroll.loans.cancel")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
