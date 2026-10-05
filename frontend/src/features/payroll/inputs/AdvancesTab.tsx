import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Ban, Check, HandCoins, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import {
  ADVANCE_STATUSES,
  useAdvances,
  useApproveAdvance,
  useCancelAdvance,
  useCreateAdvance,
  useUpdateAdvance,
  type Advance,
  type AdvanceStatus,
} from "../api";
import { formatPeriod, formatXof, monthInputValue, parseMonthInput, periodParam } from "../format";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { PayrollTable } from "../PayrollTable";
import { EmployeeSelect } from "./EmployeeSelect";

type StatusFilter = "all" | AdvanceStatus;

interface Draft {
  employeeId: string;
  amount: string;
  requestedOn: string;
  deductMonth: string;
  note: string;
}

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function formatDay(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return new Intl.DateTimeFormat(currentLocale(), { dateStyle: "medium" }).format(new Date(year, month - 1, day));
}

/** INPUT_INVALID is about the values typed, so it is shown next to them; any other refusal under the form. */
function splitRefusal(error: unknown): { field: string | null; form: string | null } {
  if (!error) return { field: null, form: null };
  if (error instanceof ApiError && error.code === "INPUT_INVALID") return { field: error.message, form: null };
  return { field: null, form: error instanceof Error ? error.message : String(error) };
}

/** An advance an approved or paid run already deducted is frozen (RUN_LOCKED). */
function locked(row: Advance): boolean {
  return row.deducted_run_status === "approved" || row.deducted_run_status === "paid";
}

export function AdvancesTab() {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("payroll.manage_inputs");
  const [status, setStatus] = useState<StatusFilter>("all");
  const advances = useAdvances(status === "all" ? undefined : status);
  const create = useCreateAdvance();
  const update = useUpdateAdvance();
  const approve = useApproveAdvance();
  const cancel = useCancelAdvance();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Advance | null>(null);
  const [cancelling, setCancelling] = useState<Advance | null>(null);
  const [draft, setDraft] = useState<Draft>({ employeeId: "", amount: "", requestedOn: today(), deductMonth: "", note: "" });
  const filters = useColumnFilters<Advance>([
    { key: "employee", kind: "text", getValue: (row) => `${row.full_name} ${row.employee_no}` },
    { key: "amount", kind: "range", getValue: (row) => row.amount },
    { key: "deductPeriod", kind: "text", getValue: (row) => formatPeriod(row.deduct_period) },
  ]);
  const dash = <span className="text-muted-foreground">—</span>;

  const mutation = editing ? update : create;
  const refusal = splitRefusal(mutation.error);
  const deductPeriod = parseMonthInput(draft.deductMonth);

  const refused = (error: unknown) => toast.error(t("payroll.advances.refused"), { description: error instanceof Error ? error.message : undefined });

  const openDialog = (row: Advance | null) => {
    create.reset();
    update.reset();
    setEditing(row);
    setDraft(
      row
        ? { employeeId: row.employee_id, amount: String(row.amount), requestedOn: row.requested_on.slice(0, 10), deductMonth: monthInputValue(row.deduct_period), note: row.note ?? "" }
        : { employeeId: "", amount: "", requestedOn: today(), deductMonth: monthInputValue(periodParam(new Date())), note: "" },
    );
    setDialogOpen(true);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const values = { amount: Number(draft.amount), requested_on: draft.requestedOn, deduct_period: deductPeriod, note: draft.note.trim() || null };
    const onSuccess = () => {
      toast.success(t(editing ? "payroll.advances.updated" : "payroll.advances.created"));
      setDialogOpen(false);
    };
    if (editing) update.mutate({ id: editing.id, changes: values }, { onSuccess });
    else create.mutate({ employee_id: draft.employeeId, ...values }, { onSuccess });
  };

  const confirmCancel = () => {
    if (!cancelling) return;
    cancel.mutate(cancelling.id, {
      onSuccess: () => {
        toast.success(t("payroll.advances.cancelled"));
        setCancelling(null);
      },
      onError: refused,
    });
  };

  const actionsFor = (row: Advance): RowAction[] =>
    row.status === "cancelled" || locked(row)
      ? []
      : [
          { key: "edit", label: t("payroll.inputs.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => openDialog(row) },
          { key: "cancel", label: t("payroll.advances.cancel"), icon: <Ban className="h-3.5 w-3.5" />, tone: "destructive", onSelect: () => setCancelling(row) },
        ];

  const columns: ColumnDef<Advance>[] = [
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
    {
      key: "amount",
      header: t("payroll.inputs.column.amount"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatXof(row.amount),
      sortValue: (row) => row.amount,
      filterCell: filters.rangeCell("amount"),
    },
    {
      key: "requestedOn",
      header: t("payroll.advances.column.requestedOn"),
      defaultWidth: 140,
      cellClassName: "tabular-nums",
      cell: (row) => formatDay(row.requested_on),
      sortValue: (row) => row.requested_on,
    },
    {
      key: "deductPeriod",
      header: t("payroll.advances.column.deductPeriod"),
      defaultWidth: 150,
      cell: (row) => <span className="capitalize">{formatPeriod(row.deduct_period)}</span>,
      sortValue: (row) => row.deduct_period,
      filterCell: filters.textCell("deductPeriod", t("payroll.advances.column.deductPeriod")),
    },
    {
      key: "status",
      header: t("payroll.advances.column.status"),
      defaultWidth: 130,
      cell: (row) => <PayrollStatusBadge domain="advance" status={row.status} />,
      sortValue: (row) => ADVANCE_STATUSES.indexOf(row.status),
    },
    {
      key: "deductedBy",
      header: t("payroll.advances.column.deductedBy"),
      defaultWidth: 220,
      cell: (row) =>
        row.deducted_run_id && row.deducted_period ? (
          <span className="flex flex-wrap items-center gap-1.5">
            <Link to={`/payroll/runs/${row.deducted_run_id}`} className="capitalize text-primary hover:underline" onClick={(event) => event.stopPropagation()}>
              {formatPeriod(row.deducted_period)}
            </Link>
            {row.deducted_run_status && <PayrollStatusBadge domain="run" status={row.deducted_run_status} />}
          </span>
        ) : (
          dash
        ),
      sortValue: (row) => row.deducted_period,
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
            defaultWidth: 150,
            alwaysVisible: true,
            cellClassName: "text-right",
            cell: (row: Advance) => (
              <div className="flex items-center justify-end gap-1">
                {row.status === "requested" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={approve.isPending}
                    onClick={() => approve.mutate(row.id, { onSuccess: () => toast.success(t("payroll.advances.approved")), onError: refused })}
                  >
                    <Check className="h-3.5 w-3.5" />
                    {t("payroll.advances.approve")}
                  </Button>
                )}
                <RowActionsMenu actions={actionsFor(row)} />
              </div>
            ),
          },
        ]
      : []),
  ];

  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("payroll.runs.filter.all") },
    ...ADVANCE_STATUSES.map((value) => ({ value, label: t(`payroll.status.advance.${value}` as TranslationKey) })),
  ];

  return (
    <div className="space-y-3">
      {advances.error && <p className="text-sm text-destructive">{advances.error instanceof ApiError ? advances.error.message : t("payroll.advances.loadError")}</p>}
      <PayrollTable
        tableKey="payroll.inputs.advances"
        columns={columns}
        rows={filters.apply(advances.data ?? [])}
        rowKey={(row) => row.id}
        loading={advances.isLoading}
        emptyTitle={t("payroll.advances.empty.title")}
        emptyDescription={t("payroll.advances.empty.description")}
        emptyIcon={<HandCoins className="h-5 w-5" />}
        toolbar={
          <>
            <FilterTabs value={status} onChange={setStatus} options={statusOptions} />
            {canWrite && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("payroll.advances.new")}
              </Button>
            )}
          </>
        }
        filtersActive={filters.isActive || status !== "all"}
        onClearFilters={() => {
          filters.reset();
          setStatus("all");
        }}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t(editing ? "payroll.advances.editTitle" : "payroll.advances.new")}</DialogTitle>
            <DialogDescription>{t("payroll.advances.dialogHint")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submit}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="advance-deduct-period">{t("payroll.advances.column.deductPeriod")}</Label>
                <Input
                  id="advance-deduct-period"
                  type="month"
                  required
                  value={draft.deductMonth}
                  onChange={(event) => setDraft((current) => ({ ...current, deductMonth: event.target.value }))}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="advance-requested-on">{t("payroll.advances.column.requestedOn")}</Label>
                <Input
                  id="advance-requested-on"
                  type="date"
                  required
                  value={draft.requestedOn}
                  onChange={(event) => setDraft((current) => ({ ...current, requestedOn: event.target.value }))}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="advance-employee">{t("payroll.inputs.column.employee")}</Label>
              {editing ? (
                <p className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-sm">
                  <span className="font-medium">{editing.full_name}</span>
                  <span className="ml-1.5 text-xs text-muted-foreground">{editing.employee_no}</span>
                </p>
              ) : (
                <EmployeeSelect id="advance-employee" period={deductPeriod} value={draft.employeeId} onChange={(employeeId) => setDraft((current) => ({ ...current, employeeId }))} />
              )}
            </div>
            {/* Review focus 4: INPUT_INVALID stays next to the amount, not only in a toast. */}
            <div className="space-y-1.5">
              <Label htmlFor="advance-amount">{t("payroll.inputs.field.amount")}</Label>
              <Input
                id="advance-amount"
                type="number"
                min={1}
                step={1}
                required
                value={draft.amount}
                error={refusal.field ?? undefined}
                onChange={(event) => setDraft((current) => ({ ...current, amount: event.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="advance-note">{t("payroll.inputs.column.note")}</Label>
              <Input id="advance-note" value={draft.note} onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value }))} />
            </div>
            {refusal.form && <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">{refusal.form}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!draft.employeeId || !draft.amount || !draft.requestedOn || !deductPeriod || mutation.isPending}>
                {mutation.isPending ? t("common.saving") : t("common.save")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={cancelling !== null} onOpenChange={(open) => !open && setCancelling(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.advances.cancelDialog.title")}</DialogTitle>
            <DialogDescription>
              {cancelling ? `${cancelling.full_name} · ${formatXof(cancelling.amount)} · ${formatPeriod(cancelling.deduct_period)}` : null}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("payroll.advances.cancelDialog.body")}</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCancelling(null)}>
              {t("payroll.inputs.keep")}
            </Button>
            <Button variant="destructive" onClick={confirmCancel} disabled={cancel.isPending}>
              <Ban className="h-4 w-4" />
              {t("payroll.advances.cancel")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
