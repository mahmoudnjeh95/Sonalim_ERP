import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { formatDuration, formatQuantity } from "../../lib/units";

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
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
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
