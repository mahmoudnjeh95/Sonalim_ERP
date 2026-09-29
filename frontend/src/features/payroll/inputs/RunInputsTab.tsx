import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight, ListChecks, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import {
  useAddRunInput,
  useDeleteRunInput,
  useInputComponents,
  useRunInputs,
  useRuns,
  useUpdateRunInput,
  type InputComponent,
  type PayrollRun,
  type RunInput,
  type RunStatus,
} from "../api";
import { formatPeriod, formatXof } from "../format";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { PayrollTable } from "../PayrollTable";
import { EmployeeSelect } from "./EmployeeSelect";

/** A run takes, changes and drops inputs only while nothing on it is approved (run_state.EDITABLE). */
const OPEN: RunStatus[] = ["draft", "calculated"];

interface Draft {
  employeeId: string;
  componentCode: string;
  qty: string;
  amount: string;
  note: string;
}

const BLANK: Draft = { employeeId: "", componentCode: "", qty: "", amount: "", note: "" };

function numberOrNull(value: string): number | null {
  const text = value.trim();
  return text === "" ? null : Number(text);
}

/** INPUT_INVALID is about the values typed, so it is shown next to them; any other refusal under the form. */
function splitRefusal(error: unknown): { field: string | null; form: string | null } {
  if (!error) return { field: null, form: null };
  if (error instanceof ApiError && error.code === "INPUT_INVALID") return { field: error.message, form: null };
  return { field: null, form: error instanceof Error ? error.message : String(error) };
}

export function RunInputsTab() {
  const { t, language } = useI18n();
  const { hasPermission } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const runs = useRuns();
  const allRuns = runs.data ?? [];
  const openRuns = allRuns.filter((run) => OPEN.includes(run.status));
  const closedRuns = allRuns.filter((run) => !OPEN.includes(run.status));
  // The run lives in the URL (?run=); without one, the latest open run, else the latest run.
  const run: PayrollRun | undefined = allRuns.find((candidate) => candidate.id === searchParams.get("run")) ?? openRuns[0] ?? allRuns[0];
  const runId = run?.id ?? "";

  const components = useInputComponents(runId || undefined);
  const inputs = useRunInputs(runId || undefined);
  const add = useAddRunInput(runId);
  const update = useUpdateRunInput(runId);
  const remove = useDeleteRunInput(runId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<RunInput | null>(null);
  const [draft, setDraft] = useState<Draft>(BLANK);
  const filters = useColumnFilters<RunInput>([
    { key: "employee", kind: "text", getValue: (row) => `${row.full_name} ${row.employee_no}` },
    { key: "component", kind: "text", getValue: (row) => `${componentName(row.component_code)} ${row.component_code}` },
    { key: "amount", kind: "range", getValue: (row) => row.amount },
  ]);

  const editable = !!run && OPEN.includes(run.status);
  const canWrite = editable && hasPermission("payroll.manage_inputs");
  const byCode = new Map((components.data ?? []).map((component) => [component.code, component]));
  function componentName(code: string): string {
    const component = byCode.get(code);
    if (!component) return code;
    return language === "fr" ? component.name_fr : component.name_en;
  }
  const number = new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 });
  const dash = <span className="text-muted-foreground">—</span>;

  const selectRun = (id: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("run", id);
    setSearchParams(next, { replace: true });
  };
  const runLabel = (candidate: PayrollRun) =>
    [formatPeriod(candidate.period), t(`payroll.runs.type.${candidate.run_type}` as TranslationKey), candidate.label, t(`payroll.status.run.${candidate.status}` as TranslationKey)]
      .filter(Boolean)
      .join(" · ");

  const mutation = editing ? update : add;
  const refusal = splitRefusal(mutation.error);
  const chosen = byCode.get(draft.componentCode);

  const openDialog = (row: RunInput | null) => {
    add.reset();
    update.reset();
    setEditing(row);
    setDraft(
      row
        ? { employeeId: row.employee_id, componentCode: row.component_code, qty: row.qty === null ? "" : String(row.qty), amount: row.amount === null ? "" : String(row.amount), note: row.note ?? "" }
        : BLANK,
    );
    setDialogOpen(true);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // A fixed component takes no quantity (the engine ignores it), so none is sent.
    const values = {
      component_code: draft.componentCode,
      qty: chosen?.formula_type === "fixed" ? null : numberOrNull(draft.qty),
      amount: numberOrNull(draft.amount),
      note: draft.note.trim() || null,
    };
    const onSuccess = () => {
      toast.success(t(editing ? "payroll.inputs.updated" : "payroll.inputs.added"));
      setDialogOpen(false);
    };
    if (editing) update.mutate({ inputId: editing.id, changes: values }, { onSuccess });
    else add.mutate({ employee_id: draft.employeeId, ...values }, { onSuccess });
  };

  const deleteInput = (row: RunInput) =>
    remove.mutate(row.id, {
      onSuccess: () => toast.success(t("payroll.inputs.deleted")),
      onError: (error) => toast.error(t("payroll.inputs.deleteRefused"), { description: error instanceof Error ? error.message : undefined }),
    });

  const actionsFor = (row: RunInput): RowAction[] => [
    { key: "edit", label: t("payroll.inputs.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => openDialog(row) },
    { key: "delete", label: t("payroll.inputs.delete"), icon: <Trash2 className="h-3.5 w-3.5" />, tone: "destructive", disabled: remove.isPending, onSelect: () => deleteInput(row) },
  ];

  const columns: ColumnDef<RunInput>[] = [
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
      key: "component",
      header: t("payroll.inputs.column.component"),
      defaultWidth: 240,
      cell: (row) => (
        <span>
          {componentName(row.component_code)}
          <span className="ml-1.5 text-xs text-muted-foreground">{row.component_code}</span>
        </span>
      ),
      sortValue: (row) => row.component_code,
      filterCell: filters.textCell("component", t("payroll.inputs.column.component")),
    },
    {
      key: "qty",
      header: t("payroll.inputs.column.qty"),
      defaultWidth: 100,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => (row.qty === null ? dash : number.format(row.qty)),
      sortValue: (row) => row.qty,
    },
    {
      key: "amount",
      header: t("payroll.inputs.column.amount"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => (row.amount === null ? dash : formatXof(row.amount)),
      sortValue: (row) => row.amount,
      filterCell: filters.rangeCell("amount"),
    },
    {
      key: "note",
      header: t("payroll.inputs.column.note"),
      defaultWidth: 220,
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
            cell: (row: RunInput) => <RowActionsMenu actions={actionsFor(row)} />,
          },
        ]
      : []),
  ];

  if (runs.isSuccess && allRuns.length === 0) {
    return (
      <EmptyState
        icon={<ListChecks className="h-5 w-5" />}
        title={t("payroll.inputs.noRun.title")}
        description={t("payroll.inputs.noRun.description")}
        action={
          <Button variant="outline" asChild>
            <Link to="/payroll/runs">{t("payroll.runs.title")}</Link>
          </Button>
        }
      />
    );
  }

  const earnings = (components.data ?? []).filter((component) => component.kind === "earning");
  const deductions = (components.data ?? []).filter((component) => component.kind === "deduction");
  const componentOptions = (list: InputComponent[]) =>
    list.map((component) => (
      <option key={component.code} value={component.code}>
        {language === "fr" ? component.name_fr : component.name_en} ({component.code})
      </option>
    ));
  const fixed = chosen?.formula_type === "fixed";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full max-w-md space-y-1.5">
          <Label htmlFor="inputs-run">{t("payroll.inputs.selectRun")}</Label>
          {runs.isLoading ? (
            <Skeleton className="h-9 w-full" />
          ) : (
            <Select id="inputs-run" value={runId} onChange={(event) => selectRun(event.target.value)}>
              {openRuns.length > 0 && <optgroup label={t("payroll.inputs.runGroup.open")}>{openRuns.map((candidate) => <option key={candidate.id} value={candidate.id}>{runLabel(candidate)}</option>)}</optgroup>}
              {closedRuns.length > 0 && <optgroup label={t("payroll.inputs.runGroup.closed")}>{closedRuns.map((candidate) => <option key={candidate.id} value={candidate.id}>{runLabel(candidate)}</option>)}</optgroup>}
            </Select>
          )}
        </div>
        {run && (
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/payroll/runs/${run.id}`}>
              <ArrowUpRight className="h-4 w-4" />
              {t("payroll.inputs.openRun")}
            </Link>
          </Button>
        )}
      </div>

      {run && !editable && (
        <p className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          <Lock className="h-4 w-4 shrink-0" aria-hidden />
          <PayrollStatusBadge domain="run" status={run.status} />
          {t("payroll.inputs.locked")}
        </p>
      )}

      <PayrollTable
        tableKey="payroll.inputs.runInputs"
        columns={columns}
        rows={filters.apply(inputs.data ?? [])}
        rowKey={(row) => row.id}
        loading={runs.isLoading || inputs.isLoading}
        emptyTitle={t("payroll.inputs.empty.title")}
        emptyDescription={t("payroll.inputs.empty.description")}
        emptyIcon={<ListChecks className="h-5 w-5" />}
        toolbar={
          canWrite && (
            <Button size="sm" onClick={() => openDialog(null)}>
              <Plus className="h-4 w-4" />
              {t("payroll.inputs.add")}
            </Button>
          )
        }
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t(editing ? "payroll.inputs.dialog.editTitle" : "payroll.inputs.dialog.addTitle")}</DialogTitle>
            <DialogDescription>{t("payroll.inputs.dialog.hint")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <Label htmlFor="run-input-employee">{t("payroll.inputs.column.employee")}</Label>
              {editing ? (
                <p className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-sm">
                  <span className="font-medium">{editing.full_name}</span>
                  <span className="ml-1.5 text-xs text-muted-foreground">{editing.employee_no}</span>
                </p>
              ) : (
                <EmployeeSelect id="run-input-employee" period={run?.period ?? ""} value={draft.employeeId} onChange={(employeeId) => setDraft((current) => ({ ...current, employeeId }))} />
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="run-input-component">{t("payroll.inputs.column.component")}</Label>
              <Select
                id="run-input-component"
                value={draft.componentCode}
                disabled={components.isLoading}
                onChange={(event) => setDraft((current) => ({ ...current, componentCode: event.target.value }))}
              >
                <option value="" disabled>
                  {t("common.select")}
                </option>
                {earnings.length > 0 && <optgroup label={t("payroll.inputs.kind.earning")}>{componentOptions(earnings)}</optgroup>}
                {deductions.length > 0 && <optgroup label={t("payroll.inputs.kind.deduction")}>{componentOptions(deductions)}</optgroup>}
              </Select>
              {components.isError && (
                <p className="text-xs text-destructive">{components.error instanceof ApiError ? components.error.message : t("payroll.inputs.noComponent")}</p>
              )}
              {components.isSuccess && components.data.length === 0 && <p className="text-xs text-muted-foreground">{t("payroll.inputs.noComponent")}</p>}
              {chosen && (
                <p className="text-xs text-muted-foreground">
                  {t(`payroll.inputs.formula.${chosen.formula_type}` as TranslationKey)}
                  {chosen.default_amount !== null && ` ${t("payroll.inputs.formula.default").replace("{amount}", formatXof(chosen.default_amount))}`}
                </p>
              )}
            </div>
            {/* Review focus 4: INPUT_INVALID stays next to the values it is about, not only in a toast. */}
            <div className="space-y-1.5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="run-input-qty">{t("payroll.inputs.field.qty")}</Label>
                  <Input
                    id="run-input-qty"
                    type="number"
                    min={0}
                    step="any"
                    value={fixed ? "" : draft.qty}
                    disabled={fixed}
                    aria-invalid={refusal.field ? true : undefined}
                    aria-describedby={refusal.field ? "run-input-error" : undefined}
                    className={refusal.field ? "border-destructive focus-visible:ring-destructive" : undefined}
                    onChange={(event) => setDraft((current) => ({ ...current, qty: event.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="run-input-amount">{t("payroll.inputs.field.amount")}</Label>
                  <Input
                    id="run-input-amount"
                    type="number"
                    min={0}
                    step={1}
                    value={draft.amount}
                    placeholder={chosen?.default_amount != null ? String(chosen.default_amount) : undefined}
                    aria-invalid={refusal.field ? true : undefined}
                    aria-describedby={refusal.field ? "run-input-error" : undefined}
                    className={refusal.field ? "border-destructive focus-visible:ring-destructive" : undefined}
                    onChange={(event) => setDraft((current) => ({ ...current, amount: event.target.value }))}
                  />
                </div>
              </div>
              {refusal.field && (
                <p id="run-input-error" role="alert" className="text-sm text-destructive">
                  {refusal.field}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="run-input-note">{t("payroll.inputs.column.note")}</Label>
              <Input id="run-input-note" value={draft.note} onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value }))} />
            </div>
            {refusal.form && <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">{refusal.form}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!draft.employeeId || !draft.componentCode || mutation.isPending}>
                {mutation.isPending ? t("common.saving") : t("common.save")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
