import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Clock, RotateCcw, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { EntryStatusBadge } from "./LedgerTable";
import { failureMessage } from "./EntriesPage";
import { errorText, formatDate, formatXof } from "./ledgerFormat";
import { LEDGER_KEYS, getSourcePostings, invalidateLedgerData, retryPostingFailure } from "./ledgerApi";

/** Run statuses after which the ledger is expected to hold the run (the approval event posts it). */
const POSTED_RUN_STATUSES = ["approved", "paid", "reversed"];

type PostingState = "posted" | "pending" | "refused";

const STATE_KEYS: Record<PostingState, TranslationKey> = {
  posted: "finance.posting.state.posted",
  pending: "finance.posting.state.pending",
  refused: "finance.posting.state.refused",
};

/** What the ledger holds for one payroll run: its entries, or why they were refused. */
export function LedgerPostingStatus({ runId, runStatus }: { runId: string; runStatus: string }) {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canRead = hasPermission("finance.view_ledger") || hasPermission("payroll.view_runs");
  const expected = POSTED_RUN_STATUSES.includes(runStatus);
  const { data, isLoading } = useQuery({
    queryKey: LEDGER_KEYS.source("payroll", runId),
    queryFn: () => getSourcePostings(token, "payroll", runId),
    enabled: canRead && expected,
  });
  const retryMutation = useMutation({
    mutationFn: (id: string) => retryPostingFailure(token, id),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.failures.retried"));
    },
    onError: (error) => toast.error(t("finance.failures.retryError"), { description: errorText(error) }),
  });

  if (!canRead || !expected) return null;
  if (isLoading || !data) return <Skeleton className="h-16 w-full" />;

  const openFailures = data.failures.filter((failure) => failure.status === "open");
  const booked = data.entries.filter((entry) => entry.status !== "draft");
  const state: PostingState = openFailures.length > 0 ? "refused" : booked.length > 0 ? "posted" : "pending";
  const Icon = state === "posted" ? CircleCheck : state === "refused" ? TriangleAlert : Clock;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 text-sm",
        state === "posted" && "border-success/30 bg-success-soft",
        state === "refused" && "border-destructive/30 bg-destructive-soft",
        state === "pending" && "border-warning/30 bg-warning-soft",
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        <Icon className="h-4 w-4" />
        {t(STATE_KEYS[state])}
      </div>
      {state === "pending" && <p className="mt-1 text-muted-foreground">{t("finance.posting.pendingHint")}</p>}
      {openFailures.map((failure) => (
        <div key={failure.id} className="mt-2 flex flex-wrap items-center gap-2">
          <span>{failureMessage(failure, language)}</span>
          {hasPermission("finance.manage_entries") && (
            <Button size="sm" variant="outline" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(failure.id)}>
              <RotateCcw className="h-3.5 w-3.5" />
              {t("finance.failures.retry")}
            </Button>
          )}
        </div>
      ))}
      {booked.length > 0 && (
        <ul className="mt-2 space-y-1">
          {booked.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-center gap-2">
              {hasPermission("finance.view_ledger") ? (
                <Link to={`/finance/entries?entry=${entry.id}`} className="font-mono text-primary hover:underline">
                  {entry.number}
                </Link>
              ) : (
                <span className="font-mono">{entry.number}</span>
              )}
              <span className="text-muted-foreground">
                {entry.journal_code} · {formatDate(entry.entry_date)} · {formatXof(entry.total_debit)}
              </span>
              <EntryStatusBadge status={entry.status} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
