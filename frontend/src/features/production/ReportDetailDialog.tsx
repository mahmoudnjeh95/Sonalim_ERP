import { useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, History, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { Skeleton } from "../../components/ui/skeleton";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { formatDuration, formatQuantity } from "../../lib/units";
import { listAuditLog, type AuditLogEntry } from "../warehouse/api";

export interface FigureRow {
  label: string;
  value: number | string | null | undefined;
  unit?: string | null;
  /** Render as a duration (min, then j/h/min) rather than a quantity. */
  duration?: boolean;
}

/**
 * Opening a report: what it says, and what may still be done to it.
 *
 * The three statuses behave differently on purpose. A **draft** belongs to the
 * team and is freely editable. A **submitted** report is at the validation desk,
 * so changing it is a validator's correction with a reason. A **validated**
 * report has already moved stock — editing or deleting it reverses those
 * movements first, which is why both demand an explanation.
 */
export function ReportDetailDialog({
  open,
  onOpenChange,
  title,
  subtitle,
  status,
  revision,
  reportId,
  figures,
  banner,
  editForm,
  onDelete,
  isDeleting,
  canDelete = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subtitle: string;
  status: string;
  revision?: number;
  /**
   * When given, a "History" action shows the full audit trail for this report
   * — every draft save, submit, correction and validation, who did it and
   * when. Shared here rather than per report type since both daily and
   * conditionnement reports write to the same `production_report` audit
   * entity.
   */
  reportId?: string;
  figures: FigureRow[];
  /**
   * Shown above the figures in view mode. For the packing report this is the
   * écart, which is a reading of the figures rather than one of them.
   */
  banner?: ReactNode;
  /** The status-appropriate edit form, or null when this report is read-only. */
  editForm?: ReactNode;
  onDelete?: (reason: string) => Promise<unknown>;
  isDeleting?: boolean;
  canDelete?: boolean;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"view" | "edit" | "delete" | "history">("view");
  const [deleteReason, setDeleteReason] = useState("");

  const deleteMutation = useMutation({
    mutationFn: () => onDelete!(deleteReason),
    onSuccess: () => {
      toast.success(t("production.reports.deleted"));
      setMode("view");
      setDeleteReason("");
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(t("production.reports.deleteError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  function close(next: boolean) {
    if (!next) {
      setMode("view");
      setDeleteReason("");
    }
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {title}
            <StatusBadge status={status} />
            {revision !== undefined && revision > 1 && (
              <span className="text-xs font-normal text-muted-foreground">
                {t("production.reports.column.revision")} {revision}
              </span>
            )}
          </DialogTitle>
          <DialogDescription>{subtitle}</DialogDescription>
        </DialogHeader>

        {mode === "view" && (
          <div className="space-y-4">
            {banner}
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-lg border border-border p-4 sm:grid-cols-2">
              {figures.map((figure) => (
                <div key={figure.label} className="flex items-baseline justify-between gap-3">
                  <dt className="text-sm text-muted-foreground">{figure.label}</dt>
                  <dd className="text-sm font-medium tabular-nums">
                    {typeof figure.value === "string"
                      ? figure.value || "—"
                      : figure.duration
                        ? formatDuration(figure.value)
                        : formatQuantity(figure.value, figure.unit)}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="flex flex-wrap gap-2">
              {editForm && (
                <Button size="sm" variant="outline" onClick={() => setMode("edit")}>
                  <Pencil className="h-3.5 w-3.5" />
                  {t("common.edit")}
                </Button>
              )}
              {reportId && (
                <Button size="sm" variant="ghost" onClick={() => setMode("history")}>
                  <History className="h-3.5 w-3.5" />
                  {t("production.reports.history.title")}
                </Button>
              )}
              {onDelete && canDelete && (
                <Button size="sm" variant="ghost" onClick={() => setMode("delete")}>
                  <Trash2 className="h-3.5 w-3.5" />
                  {t("common.delete")}
                </Button>
              )}
            </div>

            {status === "validated" && (
              <p className="text-xs text-muted-foreground">{t("production.reports.validatedNote")}</p>
            )}
          </div>
        )}

        {mode === "history" && reportId && (
          <div className="space-y-3">
            <ReportHistoryPanel reportId={reportId} />
            <Button size="sm" variant="ghost" className="w-full" onClick={() => setMode("view")}>
              {t("common.cancel")}
            </Button>
          </div>
        )}

        {mode === "edit" && (
          <div className="space-y-3">
            {editForm}
            <Button size="sm" variant="ghost" className="w-full" onClick={() => setMode("view")}>
              {t("common.cancel")}
            </Button>
          </div>
        )}

        {mode === "delete" && (
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive-soft p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <div>
                <p className="text-sm font-medium text-destructive">{t("production.reports.delete.confirm")}</p>
                <p className="text-sm text-muted-foreground">
                  {status === "validated"
                    ? t("production.reports.delete.validatedWarning")
                    : t("production.reports.delete.draftWarning")}
                </p>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="delete_reason">{t("production.reports.delete.reason")}</Label>
              <Input
                id="delete_reason"
                value={deleteReason}
                onChange={(event) => setDeleteReason(event.target.value)}
                placeholder={t("production.reports.delete.reasonPlaceholder")}
              />
              <p className="text-xs text-muted-foreground">{t("production.reports.delete.reasonHelp")}</p>
            </div>
            <div className="flex gap-2">
              <Button
                className="flex-1"
                variant="destructive"
                onClick={() => deleteMutation.mutate()}
                disabled={!deleteReason.trim() || deleteMutation.isPending || isDeleting}
              >
                <Trash2 className="h-4 w-4" />
                {deleteMutation.isPending ? t("common.saving") : t("common.delete")}
              </Button>
              <Button className="flex-1" variant="outline" onClick={() => setMode("view")}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const HISTORY_ACTIONS = [
  "created",
  "draft_updated",
  "submitted",
  "corrected",
  "corrected_after_validation",
  "validated",
  "rejected",
  "revised",
  "deleted",
] as const;

function actionSuffix(action: string): string {
  return action.split(".").pop() ?? action;
}

function formatWhen(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Who filled and edited this report, and when — every draft save, submit,
 * correction, validation, rejection and reopening. `record_audit()` already
 * writes one of these for every mutation on a report (see
 * production_report_service.py), so this is a pure read: nothing here posts
 * anything, it only surfaces a trail that already exists.
 */
function ReportHistoryPanel({ reportId }: { reportId: string }) {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data: entries, isLoading, isError } = useQuery({
    queryKey: ["core", "audit-log", "production_report", reportId],
    queryFn: () => listAuditLog(token, { entity_type: "production_report", entity_id: reportId, limit: 200 }),
  });

  function actionLabel(action: string): string {
    const suffix = actionSuffix(action);
    if ((HISTORY_ACTIONS as readonly string[]).includes(suffix)) {
      return t(`production.reports.history.action.${suffix}` as Parameters<typeof t>[0]);
    }
    return action;
  }

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (isError) {
    return <p className="text-sm text-muted-foreground">{t("production.reports.history.error")}</p>;
  }

  if (!entries || entries.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("production.reports.history.empty")}</p>;
  }

  // Newest first — what happened most recently is what someone opening this
  // panel almost always wants to see.
  const sorted = [...entries].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));

  return (
    <div className="max-h-96 space-y-2 overflow-y-auto">
      {sorted.map((entry: AuditLogEntry) => (
        <div key={entry.id} className="rounded-lg border border-border p-2.5 text-sm">
          <button
            type="button"
            className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
            onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}
          >
            <span className="font-medium">{actionLabel(entry.action)}</span>
            <span className="text-xs text-muted-foreground">
              {entry.actor_email ?? entry.actor_id} · {formatWhen(entry.occurred_at, language)}
            </span>
          </button>
          {expanded === entry.id && (
            <pre className="mt-2 max-h-48 overflow-auto rounded bg-muted/50 p-2 text-xs">
              {JSON.stringify(entry.payload, null, 2)}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
