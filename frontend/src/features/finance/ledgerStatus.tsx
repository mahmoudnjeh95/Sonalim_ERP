import type * as React from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleDashed, CircleOff, RotateCcw, TriangleAlert, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { errorText } from "./ledgerFormat";
import { invalidateLedgerData, retryPostingFailure } from "./ledgerApi";

/** Where a document stands in the ledger (POST /finance/ledger-status). */
export const LEDGER_STATUSES = ["posted", "failed", "reversed", "not_posted", "off"] as const;
export type LedgerStatusValue = (typeof LEDGER_STATUSES)[number];
export type LedgerSourceModule = "treasury" | "procurement" | "finance" | "payroll";

type LedgerEntryRef = { id: string; number: string | null; entry_date: string };
type LedgerFailure = { id: string; source_kind: string; code: string; message: string; message_fr: string };

/** One part of a treasury document: its own entries, or an instrument's collection, unpaid or fee. */
export interface LedgerStatusPart {
  part: "document" | "collection" | "unpaid" | "rejection_fee";
  instrument_number: string | null;
  status: LedgerStatusValue;
  entries: LedgerEntryRef[];
  failure: LedgerFailure | null;
}

export interface DocumentLedgerStatus {
  status: LedgerStatusValue;
  entries: LedgerEntryRef[];
  failure: LedgerFailure | null;
  parts: LedgerStatusPart[];
}

const PART_KEYS: Record<LedgerStatusPart["part"], TranslationKey> = {
  document: "finance.ledgerStatus.part.document",
  collection: "finance.ledgerStatus.part.collection",
  unpaid: "finance.ledgerStatus.part.unpaid",
  rejection_fee: "finance.ledgerStatus.part.rejection_fee",
};

/** Which permission lets a user see a module's documents, and so their ledger status. */
const READERS: Record<LedgerSourceModule, string> = {
  treasury: "treasury.view",
  procurement: "procurement.view_purchase_invoices",
  finance: "finance.view_invoices",
  payroll: "payroll.view_runs",
};

const LABEL_KEYS: Record<LedgerStatusValue, TranslationKey> = {
  posted: "finance.ledgerStatus.posted",
  failed: "finance.ledgerStatus.failed",
  reversed: "finance.ledgerStatus.reversed",
  not_posted: "finance.ledgerStatus.not_posted",
  off: "finance.ledgerStatus.off",
};

const VARIANTS = { posted: "success", failed: "destructive", reversed: "default", not_posted: "warning", off: "default" } as const;
const ICONS = { posted: CircleCheck, failed: TriangleAlert, reversed: Undo2, not_posted: CircleDashed, off: CircleOff } as const;

export function ledgerStatusLabelKey(status: LedgerStatusValue): TranslationKey {
  return LABEL_KEYS[status];
}

export function getLedgerStatuses(token: string, sourceModule: LedgerSourceModule, ids: string[]) {
  return apiFetch<{ statuses: Record<string, DocumentLedgerStatus> }>("/finance/ledger-status", {
    method: "POST",
    token,
    body: { source_module: sourceModule, ids },
  });
}

/** Under the ledger's "sources" key, so invalidateLedgerData() refreshes it after a retry or a posting. */
export function ledgerStatusKey(sourceModule: LedgerSourceModule, ids: string[]) {
  return ["finance", "ledger", "sources", "status", sourceModule, ids] as const;
}

/** One request for every document on the page. Empty while loading or when the user can't see the module. */
export function useLedgerStatuses(sourceModule: LedgerSourceModule, ids: string[]): Record<string, DocumentLedgerStatus> {
  const { session, hasPermission } = useAuth();
  const allowed = hasPermission(READERS[sourceModule]) || hasPermission("finance.view_ledger");
  const sorted = [...new Set(ids)].sort();
  const { data } = useQuery({
    queryKey: ledgerStatusKey(sourceModule, sorted),
    queryFn: () => getLedgerStatuses(session!.token, sourceModule, sorted),
    enabled: allowed && sorted.length > 0,
  });
  return data?.statuses ?? {};
}

/**
 * The badge in a list or a detail view. Posted links to the entry (for ledger readers); refused opens the
 * ledger's reason and, for users who may, a retry.
 */
export function LedgerStatusBadge({ status }: { status: DocumentLedgerStatus | undefined }) {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const queryClient = useQueryClient();
  const retryMutation = useMutation({
    mutationFn: (failureId: string) => retryPostingFailure(session!.token, failureId),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.failures.retried"));
    },
    onError: (error) => toast.error(t("finance.failures.retryError"), { description: errorText(error) }),
  });
  if (!status) return null;
  const canReadLedger = hasPermission("finance.view_ledger");
  const canRetry = hasPermission("finance.manage_entries");
  const badge = <StatusPill status={status.status} />;
  const entryLink = (entry: LedgerEntryRef, children: React.ReactNode) =>
    canReadLedger ? (
      <Link to={`/finance/entries?entry=${encodeURIComponent(entry.id)}`} onClick={(event) => event.stopPropagation()}>
        {children}
      </Link>
    ) : (
      children
    );
  const reason = (failure: LedgerFailure) => (language === "fr" ? failure.message_fr : failure.message);
  const retry = (failure: LedgerFailure) =>
    canRetry && (
      <Button size="sm" variant="outline" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(failure.id)}>
        <RotateCcw className="h-3.5 w-3.5" />
        {t("finance.failures.retry")}
      </Button>
    );

  // A treasury document with instruments: every part, its status, its entries and any refusal.
  if (status.parts.length > 1) {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" className="cursor-pointer" onClick={(event) => event.stopPropagation()}>
            {badge}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-96 space-y-2 text-sm" onClick={(event) => event.stopPropagation()}>
          <p className="font-medium">{t("finance.ledgerStatus.parts")}</p>
          <ul className="space-y-2" data-ledger-parts>
            {status.parts.map((part, index) => (
              <li key={index} className="space-y-1 rounded-md border px-2 py-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    {t(PART_KEYS[part.part])}
                    {part.instrument_number && <span className="text-muted-foreground"> · {part.instrument_number}</span>}
                  </span>
                  <StatusPill status={part.status} />
                </div>
                {part.entries.length > 0 && (
                  <div className="flex flex-wrap gap-2 font-mono text-xs">
                    {part.entries.map((entry) => (
                      <span key={entry.id}>{entryLink(entry, <span className="underline-offset-2 hover:underline">{entry.number ?? entry.id}</span>)}</span>
                    ))}
                  </div>
                )}
                {part.failure && (
                  <div className="space-y-1">
                    <p className="text-muted-foreground">{reason(part.failure)}</p>
                    {retry(part.failure)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    );
  }
  if (status.status === "posted" || status.status === "reversed") {
    const entry = status.entries[0];
    if (!entry || !canReadLedger) return badge;
    return <span title={status.entries.map((e) => e.number ?? e.id).join(", ")}>{entryLink(entry, badge)}</span>;
  }
  if (status.status === "failed" && status.failure) {
    const failure = status.failure;
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" className="cursor-pointer" onClick={(event) => event.stopPropagation()}>
            {badge}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-80 space-y-2 text-sm" onClick={(event) => event.stopPropagation()}>
          <p className="font-medium">{t("finance.ledgerStatus.refusedBecause")}</p>
          <p className="text-muted-foreground">{reason(failure)}</p>
          {retry(failure)}
        </PopoverContent>
      </Popover>
    );
  }
  return badge;
}

function StatusPill({ status }: { status: LedgerStatusValue }) {
  const { t } = useI18n();
  const Icon = ICONS[status];
  return (
    <Badge variant={VARIANTS[status]} data-ledger-status={status}>
      <Icon className="h-3 w-3" />
      {t(LABEL_KEYS[status])}
    </Badge>
  );
}

/** For list filters: "all" plus each status; documents with no status yet (loading) match only "all". */
export type LedgerStatusFilter = "all" | LedgerStatusValue;

export function matchesLedgerFilter(filter: LedgerStatusFilter, status: DocumentLedgerStatus | undefined): boolean {
  return filter === "all" || status?.status === filter;
}

/** The filter pills above a list: all, then one per status. */
export function LedgerStatusFilterTabs({ value, onChange }: { value: LedgerStatusFilter; onChange: (value: LedgerStatusFilter) => void }) {
  const { t } = useI18n();
  return (
    <FilterTabs<LedgerStatusFilter>
      value={value}
      onChange={onChange}
      options={[
        { value: "all", label: t("finance.ledgerStatus.filterAll") },
        ...LEDGER_STATUSES.map((status) => ({ value: status, label: t(LABEL_KEYS[status]) })),
      ]}
    />
  );
}
