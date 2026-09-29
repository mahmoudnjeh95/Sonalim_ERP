import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, Banknote, CheckCircle2, Download, FileCog, Printer, RefreshCw, X } from "lucide-react";
import { FilterTabs } from "../../../../components/patterns/FilterTabs";
import { Button } from "../../../../components/ui/button";
import { ApiError } from "../../../../lib/api";
import { useAuth } from "../../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../../lib/i18n";
import type { ColumnDef } from "../../../../lib/useTableColumns";
import {
  BATCH_STATUSES,
  batchFileUrl,
  fetchPayrollFile,
  useBankTemplates,
  useConfirmBatch,
  useGeneratePayouts,
  useMarkPaid,
  usePayoutBatches,
  type BatchStatus,
  type PayoutBatch,
  type PayrollRun,
} from "../../api";
import { formatXof } from "../../format";
import { PayrollStatusBadge } from "../../PayrollStatusBadge";
import { PayrollTable } from "../../PayrollTable";
import { BankTemplatesDialog } from "./BankTemplatesDialog";

type StatusFilter = "all" | BatchStatus;

/** A refused generation, kept on screen: PAYOUT_SPLIT_INVALID names every employee to fix. */
interface Refusal {
  title: string;
  message: string;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Saves a downloaded file; the server's Content-Disposition is not readable across origins, so the name is ours. */
function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * The payout batches of an approved run: one per bank, per mobile-money operator and one for cash.
 * Files and cash sheets come from here; confirming every batch is what lets the run be marked paid.
 */
export function PayoutsPanel({ run }: { run: PayrollRun }) {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const canPay = hasPermission("payroll.pay_runs");
  const { data: batches = [], isLoading } = usePayoutBatches(run.id);
  const { data: templates = [], isSuccess: templatesLoaded } = useBankTemplates();
  const generate = useGeneratePayouts(run.id);
  const confirm = useConfirmBatch(run.id);
  const markPaid = useMarkPaid();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [templateBank, setTemplateBank] = useState<string | null>(null);

  const approved = run.status === "approved";
  const anyConfirmed = batches.some((batch) => batch.status === "confirmed");
  const allConfirmed = batches.length > 0 && batches.every((batch) => batch.status === "confirmed");
  // Both sides are upper-cased by the server, so a bank's template matches its batch key exactly.
  const templateBanks = new Set(templates.map((template) => template.bank_name));
  const templateMissing = (batch: PayoutBatch) => batch.method === "bank" && templatesLoaded && !templateBanks.has(batch.group_key);
  const missingText = (bank: string) => t("payroll.payouts.templateMissing").replace("{bank}", bank);

  const openTemplates = (bank: string | null) => {
    setTemplateBank(bank);
    setTemplatesOpen(true);
  };

  const onGenerate = () => {
    setRefusal(null);
    generate.mutate(undefined, {
      onSuccess: () => toast.success(t("payroll.payouts.generated")),
      onError: (error) => {
        // The server's message is shown as is: it names each employee whose payment split is wrong.
        const next = { title: t("payroll.payouts.generateRefused"), message: errorText(error) };
        setRefusal(next);
        toast.error(next.title, { description: next.message });
      },
    });
  };

  const onConfirm = (batch: PayoutBatch) =>
    confirm.mutate(batch.id, {
      onSuccess: () => toast.success(t("payroll.payouts.confirmed")),
      onError: (error) => toast.error(t("payroll.payouts.confirmRefused"), { description: errorText(error) }),
    });

  const onMarkPaid = () =>
    markPaid.mutate(run.id, {
      onSuccess: () => toast.success(t("payroll.run.markedPaidToast")),
      onError: (error) => toast.error(t("payroll.run.markPaidRefused"), { description: errorText(error) }),
    });

  const download = async (batch: PayoutBatch) => {
    setDownloading(batch.id);
    try {
      saveBlob(await fetchPayrollFile(session?.token ?? "", batchFileUrl(batch.id)), batch.file_name);
    } catch (error) {
      // No template for this bank: send the user to add one rather than leave them with a refusal.
      if (error instanceof ApiError && error.code === "TEMPLATE_MISSING") {
        toast.error(missingText(batch.group_key), { description: error.message });
        openTemplates(batch.group_key);
      } else {
        toast.error(t("payroll.payouts.downloadRefused"), { description: errorText(error) });
      }
    } finally {
      setDownloading(null);
    }
  };

  const methodLabel = (batch: PayoutBatch) => t(`payroll.payouts.method.${batch.method}` as TranslationKey);

  const columns: ColumnDef<PayoutBatch>[] = [
    {
      key: "method",
      header: t("payroll.payouts.column.method"),
      cell: methodLabel,
      defaultWidth: 150,
      sortValue: methodLabel,
    },
    {
      key: "group",
      header: t("payroll.payouts.column.group"),
      cell: (row) =>
        row.method === "cash" ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <div className="space-y-1">
            <span className="font-medium">{row.group_key}</span>
            {templateMissing(row) && (
              <div className="flex items-start gap-1 text-xs text-warning">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                <span>
                  {missingText(row.group_key)}
                  {canPay && (
                    <button type="button" className="ml-1 font-medium underline underline-offset-2 hover:text-foreground" onClick={() => openTemplates(row.group_key)}>
                      {t("payroll.payouts.addTemplate")}
                    </button>
                  )}
                </span>
              </div>
            )}
          </div>
        ),
      defaultWidth: 280,
      sortValue: (row) => row.group_key,
    },
    {
      key: "lines",
      header: t("payroll.payouts.column.lines"),
      cell: (row) => row.line_count,
      defaultWidth: 100,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      sortValue: (row) => row.line_count,
    },
    {
      key: "total",
      header: t("payroll.payouts.column.total"),
      cell: (row) => formatXof(row.total),
      defaultWidth: 160,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      sortValue: (row) => row.total,
    },
    {
      key: "status",
      header: t("payroll.payouts.column.status"),
      cell: (row) => <PayrollStatusBadge domain="payslipBatch" status={row.status} />,
      defaultWidth: 130,
      sortValue: (row) => BATCH_STATUSES.indexOf(row.status),
    },
    // Files, cash sheets and confirmation all need payroll.pay_runs; a reader sees the batches only.
    ...(canPay
      ? [
          {
            key: "actions",
            header: "",
            alwaysVisible: true,
            defaultWidth: 260,
            cellClassName: "text-right",
            cell: (row: PayoutBatch) => (
              <div className="flex flex-wrap justify-end gap-1">
                {row.method === "cash" ? (
                  <Button size="sm" variant="outline" asChild>
                    <Link to={`/payroll/payout-batches/${row.id}/cash-sheet/print`}>
                      <Printer className="h-4 w-4" />
                      {t("payroll.payouts.cashSheet")}
                    </Link>
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" disabled={downloading === row.id} onClick={() => void download(row)}>
                    <Download className="h-4 w-4" />
                    {t("payroll.payouts.download")}
                  </Button>
                )}
                {row.status === "generated" && (
                  <Button size="sm" disabled={confirm.isPending} onClick={() => onConfirm(row)}>
                    <CheckCircle2 className="h-4 w-4" />
                    {t("payroll.payouts.confirm")}
                  </Button>
                )}
              </div>
            ),
          },
        ]
      : []),
  ];

  const counts = (value: StatusFilter) => (value === "all" ? batches.length : batches.filter((batch) => batch.status === value).length);
  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: `${t("payroll.payouts.filter.all")} (${counts("all")})` },
    ...BATCH_STATUSES.map((value) => ({ value, label: `${t(`payroll.status.payslipBatch.${value}` as const)} (${counts(value)})` })),
  ];
  const rows = status === "all" ? batches : batches.filter((batch) => batch.status === status);

  // Batches are (re)generated for an approved run until the first one is confirmed.
  const canGenerate = canPay && approved && !anyConfirmed;

  return (
    <div className="space-y-3">
      {refusal && (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive-soft p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <div className="flex-1">
            <p className="font-medium text-destructive">{refusal.title}</p>
            <p className="text-foreground">{refusal.message}</p>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label={t("payroll.run.dismiss")}
            onClick={() => setRefusal(null)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {canPay && approved && allConfirmed && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-success/30 bg-success-soft px-3 py-2 text-sm">
          <span className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
            {t("payroll.payouts.readyToPay")}
          </span>
          <Button size="sm" onClick={onMarkPaid} disabled={markPaid.isPending}>
            <Banknote className="h-4 w-4" />
            {t("payroll.run.markPaid")}
          </Button>
        </div>
      )}
      {canPay && approved && batches.length > 0 && !allConfirmed && <p className="text-xs text-muted-foreground">{t("payroll.payouts.hint")}</p>}
      <PayrollTable
        tableKey="payroll.run.payouts"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.payouts.empty.title")}
        emptyDescription={canGenerate ? t("payroll.payouts.empty.ready") : t("payroll.payouts.empty.description")}
        emptyIcon={<Banknote className="h-5 w-5" />}
        filtersActive={status !== "all"}
        onClearFilters={() => setStatus("all")}
        toolbar={
          <>
            <FilterTabs value={status} onChange={setStatus} options={statusOptions} />
            {canGenerate && (
              <Button size="sm" variant={batches.length === 0 ? "default" : "outline"} onClick={onGenerate} disabled={generate.isPending}>
                {batches.length === 0 ? <Banknote className="h-4 w-4" /> : <RefreshCw className="h-4 w-4" />}
                {batches.length === 0 ? t("payroll.payouts.generate") : t("payroll.payouts.regenerate")}
              </Button>
            )}
            {canPay && (
              <Button size="sm" variant="outline" onClick={() => openTemplates(null)}>
                <FileCog className="h-4 w-4" />
                {t("payroll.payouts.templates.manage")}
              </Button>
            )}
          </>
        }
      />
      <BankTemplatesDialog open={templatesOpen} onOpenChange={setTemplatesOpen} bankName={templateBank} canEdit={canPay} />
    </div>
  );
}
