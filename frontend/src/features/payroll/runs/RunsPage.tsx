import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, Plus, ReceiptText, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { RUN_STATUSES, useDeleteRun, useRuns, type PayrollRun, type RunStatus } from "../api";
import { formatPeriod, formatXof } from "../format";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { PayrollTable } from "../PayrollTable";
import { RunDialog } from "./RunDialog";

type StatusFilter = "all" | RunStatus;

/** A run can still be deleted while nothing on it is approved (run_state.EDITABLE). */
const DELETABLE: RunStatus[] = ["draft", "calculated"];

export function RunsPage() {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const navigate = useNavigate();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState<PayrollRun | null>(null);
  const runs = useRuns(status === "all" ? undefined : status);
  const deleteRun = useDeleteRun();
  const canWrite = hasPermission("payroll.calculate_runs");

  const typeLabel = (row: PayrollRun) => t(`payroll.runs.type.${row.run_type}` as const);
  const describe = (row: PayrollRun) => [formatPeriod(row.period), typeLabel(row), row.label].filter(Boolean).join(" · ");

  const filters = useColumnFilters<PayrollRun>([
    { key: "period", kind: "text", getValue: (row) => formatPeriod(row.period) },
    { key: "type", kind: "text", getValue: typeLabel },
    { key: "label", kind: "text", getValue: (row) => row.label },
    { key: "payslips", kind: "range", getValue: (row) => row.payslip_count },
    { key: "gross", kind: "range", getValue: (row) => row.gross },
    { key: "net", kind: "range", getValue: (row) => row.net },
  ]);
  const rows = filters.apply(runs.data ?? []);

  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("payroll.runs.filter.all") },
    ...RUN_STATUSES.map((value) => ({ value, label: t(`payroll.status.run.${value}` as const) })),
  ];

  const clearFilters = () => {
    filters.reset();
    setStatus("all");
  };

  const confirmDelete = () => {
    if (!deleting) return;
    deleteRun.mutate(deleting.id, {
      onSuccess: () => {
        toast.success(t("payroll.runs.deleted"));
        setDeleting(null);
      },
      onError: (error) => toast.error(t("payroll.runs.deleteError"), { description: error instanceof ApiError ? error.message : undefined }),
    });
  };

  const actionsFor = (row: PayrollRun): RowAction[] =>
    DELETABLE.includes(row.status)
      ? [{ key: "delete", label: t("payroll.runs.action.delete"), icon: <Trash2 className="h-3.5 w-3.5" />, tone: "destructive", onSelect: () => setDeleting(row) }]
      : [];

  const columns: ColumnDef<PayrollRun>[] = [
    {
      key: "period",
      header: t("payroll.runs.column.period"),
      defaultWidth: 160,
      cell: (row) => <span className="font-medium capitalize">{formatPeriod(row.period)}</span>,
      filterCell: filters.textCell("period", t("payroll.runs.column.period")),
      sortValue: (row) => row.period,
    },
    {
      key: "type",
      header: t("payroll.runs.column.type"),
      defaultWidth: 120,
      cell: typeLabel,
      filterCell: filters.textCell("type", t("payroll.runs.column.type")),
      sortValue: (row) => row.run_type,
    },
    {
      key: "label",
      header: t("payroll.runs.column.label"),
      defaultWidth: 180,
      cell: (row) => row.label ?? <span className="text-muted-foreground">—</span>,
      filterCell: filters.textCell("label", t("payroll.runs.column.label")),
      sortValue: (row) => row.label,
    },
    {
      key: "status",
      header: t("payroll.runs.column.status"),
      defaultWidth: 230,
      cell: (row) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <PayrollStatusBadge domain="run" status={row.status} />
          {/* Review focus 1: a run calculated under a draft rule set says so on the list too. */}
          {row.rule_set_status === "draft" && (
            <Badge variant="warning" title={t("payroll.runs.draftRulesHint")}>
              <AlertTriangle className="h-3 w-3" />
              {t("payroll.runs.draftRules")}
            </Badge>
          )}
        </div>
      ),
      sortValue: (row) => RUN_STATUSES.indexOf(row.status),
    },
    {
      key: "payslips",
      header: t("payroll.runs.column.payslips"),
      defaultWidth: 110,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => row.payslip_count,
      filterCell: filters.rangeCell("payslips"),
      sortValue: (row) => row.payslip_count,
    },
    {
      key: "gross",
      header: t("payroll.runs.column.gross"),
      defaultWidth: 160,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatXof(row.gross),
      filterCell: filters.rangeCell("gross"),
      sortValue: (row) => row.gross,
    },
    {
      key: "net",
      header: t("payroll.runs.column.net"),
      defaultWidth: 160,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatXof(row.net),
      filterCell: filters.rangeCell("net"),
      sortValue: (row) => row.net,
    },
    {
      key: "warnings",
      header: t("payroll.runs.column.warnings"),
      defaultWidth: 120,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) =>
        row.warning_count > 0 ? (
          <span className="inline-flex items-center gap-1 font-medium text-warning" title={t("payroll.runs.warningsHint")}>
            <AlertTriangle className="h-3.5 w-3.5" />
            {row.warning_count}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      sortValue: (row) => row.warning_count,
    },
    ...(canWrite
      ? [
          {
            key: "actions",
            header: "",
            defaultWidth: 70,
            alwaysVisible: true,
            cellClassName: "text-right",
            cell: (row: PayrollRun) => <RowActionsMenu actions={actionsFor(row)} />,
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("payroll.runs.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("payroll.runs.subtitle")}</p>
        </div>
        {canWrite && (
          <Button onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("payroll.runs.new")}
          </Button>
        )}
      </motion.div>

      <Card>
        <CardContent className="space-y-3 pt-6">
          {runs.error && (
            <p className="text-sm text-destructive">{runs.error instanceof ApiError ? runs.error.message : t("payroll.runs.loadError")}</p>
          )}
          <PayrollTable
            tableKey="payroll.runs"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            loading={runs.isLoading}
            emptyTitle={t("payroll.runs.empty.title")}
            emptyDescription={t("payroll.runs.empty.description")}
            emptyIcon={<ReceiptText className="h-5 w-5" />}
            toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
            filtersActive={filters.isActive || status !== "all"}
            onClearFilters={clearFilters}
            onRowClick={(row) => navigate(`/payroll/runs/${row.id}`)}
          />
        </CardContent>
      </Card>

      <RunDialog open={dialogOpen} onOpenChange={setDialogOpen} />

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.runs.deleteDialog.title")}</DialogTitle>
            <DialogDescription className="first-letter:uppercase">{deleting ? describe(deleting) : null}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("payroll.runs.deleteDialog.body")}</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              {t("common.cancel")}
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleteRun.isPending}>
              <Trash2 className="h-4 w-4" />
              {t("common.delete")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
