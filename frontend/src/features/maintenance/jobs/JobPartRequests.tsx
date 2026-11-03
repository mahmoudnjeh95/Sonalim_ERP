import type { ReactNode } from "react";
import { PackageSearch } from "lucide-react";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import type { JobDetail, PartRequest } from "../api";
import { formatDateTime } from "./jobFormat";

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

/**
 * The job page's spare-parts block — the slot Task F7 fills.
 *
 * Today it lists the job's requests read-only, straight from
 * `JobDetail.part_requests`. F7 passes its "Demander des pièces" button (and
 * the dialog it opens) through `action`, and can swap the plain rows below for
 * its own `PartRequestCard`. Every maintenance mutation invalidates the
 * `["maintenance"]` query prefix, so a new or decided request shows up here
 * without this component doing anything.
 */
export function JobPartRequests({ job, action }: { job: JobDetail; action?: ReactNode }) {
  const { t } = useI18n();
  const requests = job.part_requests;

  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <PackageSearch className="h-4 w-4 text-muted-foreground" />
            {t("maintenance.jobs.parts.title")}
          </CardTitle>
          <CardDescription>{t("maintenance.jobs.parts.description")}</CardDescription>
        </div>
        {action}
      </CardHeader>
      <CardContent>
        {requests.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("maintenance.jobs.parts.empty")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {requests.map((request) => (
              <li key={request.id} className="space-y-2 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Badge variant={STATUS_VARIANT[request.status]} dot>
                    {t(STATUS_LABEL_KEY[request.status])}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {request.requested_by_name} · {formatDateTime(request.requested_at)}
                  </span>
                </div>
                <ul className="space-y-0.5 text-sm">
                  {request.lines.map((line) => (
                    <li key={line.id} className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 break-words">{line.product_name}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{formatQuantity(line.quantity, line.uom_code)}</span>
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
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
