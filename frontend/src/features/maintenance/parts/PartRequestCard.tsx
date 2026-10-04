import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Label } from "../../../components/ui/label";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import { apiErrorMessage, formatDateTime } from "../jobs/jobFormat";
import { useRejectPartRequest, type PartRequest } from "../api";
import { listLocations } from "../../warehouse/api";
import { ApproveDialog } from "./ApproveDialog";

const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

const STATUS_LABEL_KEY: Record<PartRequest["status"], TranslationKey> = {
  pending: "maintenance.jobs.parts.status.pending",
  approved: "maintenance.jobs.parts.status.approved",
  rejected: "maintenance.jobs.parts.status.rejected",
};

const STATUS_VARIANT: Record<PartRequest["status"], BadgeProps["variant"]> = {
  pending: "warning",
  approved: "success",
  rejected: "destructive",
};

function RejectDialog({ request, open, onOpenChange }: { request: PartRequest; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const reject = useRejectPartRequest(token);
  const [note, setNote] = useState("");

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setNote("");
          reject.reset();
        }
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("maintenance.parts.reject.title")}</DialogTitle>
          <DialogDescription>{t("maintenance.parts.reject.description").replace("{number}", request.job_number)}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="reject-note">{t("maintenance.parts.reject.field.note")}</Label>
            <textarea
              id="reject-note"
              rows={3}
              autoFocus
              required
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={t("maintenance.parts.reject.field.note.placeholder")}
              className={TEXTAREA_CLASS}
            />
          </div>
          {reject.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(reject.error, t("maintenance.parts.reject.error"))}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!note.trim() || reject.isPending}
              onClick={() =>
                reject.mutate(
                  { partRequestId: request.id, note: note.trim() },
                  {
                    onSuccess: () => {
                      toast.success(t("maintenance.parts.reject.done"));
                      onOpenChange(false);
                    },
                  },
                )
              }
            >
              {reject.isPending ? t("maintenance.parts.reject.saving") : t("maintenance.parts.reject.submit")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * One spare-parts request in the Parts tab: job (links to the job page),
 * machine, requester, date, every line with its requested quantity and, once
 * decided, what was issued from stock and what is left to order. A pending
 * request shows the supervisor's Valider/Refuser actions when `canDecide`.
 */
export function PartRequestCard({ request, canDecide }: { request: PartRequest; canDecide: boolean }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  // Only needed to turn an approved line's location_id into a readable name below.
  const hasIssuedLine = request.status === "approved" && request.lines.some((line) => line.location_id);
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token), enabled: hasIssuedLine });
  const locationName = (id: string) => locations.find((location) => location.id === id)?.name ?? id;

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 space-y-0.5">
            <Link to={`/maintenance/jobs/${request.job_id}`} className="font-mono text-xs font-medium text-primary hover:underline">
              {request.job_number}
            </Link>
            <p className="break-words text-sm font-medium">{request.equipment_name}</p>
            <p className="text-xs text-muted-foreground">
              {request.requested_by_name} · {formatDateTime(request.requested_at)}
            </p>
          </div>
          <Badge variant={STATUS_VARIANT[request.status]} dot>
            {t(STATUS_LABEL_KEY[request.status])}
          </Badge>
        </div>

        <ul className="space-y-1.5 text-sm">
          {request.lines.map((line) => (
            <li key={line.id} className="space-y-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 break-words">{line.product_name}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{formatQuantity(line.quantity, line.uom_code)}</span>
              </div>
              {request.status === "approved" && (
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                  {(line.issued_quantity ?? 0) > 0 && (
                    <span className="text-success">
                      {t("maintenance.parts.line.issued")}: {formatQuantity(line.issued_quantity, line.uom_code)}
                      {line.location_id && ` @ ${locationName(line.location_id)}`}
                    </span>
                  )}
                  {(line.purchase_quantity ?? 0) > 0 && (
                    <span className="text-warning">
                      {t("maintenance.parts.line.toOrder")}: {formatQuantity(line.purchase_quantity, line.uom_code)}
                    </span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>

        {request.note && <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{request.note}</p>}
        {request.decision_note && (
          <p className="whitespace-pre-wrap break-words text-sm">
            <span className="text-muted-foreground">{t("maintenance.jobs.parts.decisionNote")} : </span>
            {request.decision_note}
          </p>
        )}
        {request.decided_by_name && (
          <p className="text-xs text-muted-foreground">
            {request.decided_by_name} · {formatDateTime(request.decided_at)}
          </p>
        )}

        {canDecide && request.status === "pending" && (
          <div className="flex flex-col-reverse gap-2 border-t border-border pt-3 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" className="h-10 text-destructive hover:bg-destructive-soft sm:h-9" onClick={() => setRejectOpen(true)}>
              <XCircle className="h-4 w-4" />
              {t("maintenance.parts.action.reject")}
            </Button>
            <Button type="button" className="h-10 sm:h-9" onClick={() => setApproveOpen(true)}>
              <CheckCircle2 className="h-4 w-4" />
              {t("maintenance.parts.action.approve")}
            </Button>
          </div>
        )}
      </CardContent>

      <ApproveDialog request={approveOpen ? request : null} open={approveOpen} onOpenChange={setApproveOpen} />
      <RejectDialog request={request} open={rejectOpen} onOpenChange={setRejectOpen} />
    </Card>
  );
}
