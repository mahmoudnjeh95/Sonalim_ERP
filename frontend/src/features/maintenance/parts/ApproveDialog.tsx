import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "../../../components/ui/button";
import { Label } from "../../../components/ui/label";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Skeleton } from "../../../components/ui/skeleton";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import { apiErrorMessage } from "../jobs/jobFormat";
import { useApprovePartRequest, usePartRequestAvailability, type ApprovePartRequestLineInput, type PartRequest } from "../api";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

interface LineState {
  location_id: string;
  issue_quantity: string;
}

/**
 * The supervisor's approval dialog: per line, stock availability by location
 * (`GET /part-requests/{id}/availability`), a location to issue from, and how
 * much to issue there — never more than that location holds
 * (`INSUFFICIENT_STOCK` otherwise) and a location is required whenever the
 * issued quantity is above zero (`LOCATION_REQUIRED`). What is left after the
 * issued quantity (`quantity - issue_quantity`) shows as "à commander" — the
 * backend turns it into a draft purchase order on approval.
 */
export function ApproveDialog({
  request,
  open,
  onOpenChange,
}: {
  request: PartRequest | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const { data: availability, isLoading: availabilityLoading } = usePartRequestAvailability(token, open ? (request?.id ?? null) : null);
  const approve = useApprovePartRequest(token);

  const [lineState, setLineState] = useState<Record<string, LineState>>({});
  const [note, setNote] = useState("");

  // Reset when a different request opens, and once its availability arrives pre-fill each
  // line's location with its best-stocked spare-parts location (the best-stocked one anywhere
  // when the spare-parts location has none) and the quantity with min(requested, available there).
  useEffect(() => {
    if (!open) return;
    setNote("");
    approve.reset();
    setLineState({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, request?.id]);

  useEffect(() => {
    if (!open || !request || !availability) return;
    setLineState((current) => {
      if (Object.keys(current).length > 0) return current;
      const next: Record<string, LineState> = {};
      for (const line of request.lines) {
        const locations = availability.lines.find((entry) => entry.line_id === line.id)?.locations ?? [];
        const byStock = locations.slice().sort((a, b) => b.available - a.available);
        const best = byStock.find((location) => location.in_spare_parts) ?? byStock[0] ?? null;
        const defaultIssue = best ? Math.min(line.quantity, best.available) : 0;
        next[line.id] = {
          location_id: best && defaultIssue > 0 ? best.location_id : "",
          issue_quantity: defaultIssue > 0 ? String(defaultIssue) : "0",
        };
      }
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, request, availability]);

  const availableByLine = useMemo(() => {
    const map = new Map<string, { location_id: string; location_name: string; available: number }[]>();
    // The spare-parts location and the ones under it first, each group in the server's (name) order.
    for (const line of availability?.lines ?? []) {
      map.set(line.line_id, [...line.locations.filter((l) => l.in_spare_parts), ...line.locations.filter((l) => !l.in_spare_parts)]);
    }
    return map;
  }, [availability]);

  if (!request) return null;

  function updateLine(lineId: string, patch: Partial<LineState>) {
    setLineState((current) => ({ ...current, [lineId]: { ...current[lineId], ...patch } }));
  }

  function handleLocationChange(lineId: string, locationId: string, requestedQuantity: number) {
    const locations = availableByLine.get(lineId) ?? [];
    const chosen = locations.find((entry) => entry.location_id === locationId);
    const defaultIssue = chosen ? Math.min(requestedQuantity, chosen.available) : 0;
    updateLine(lineId, { location_id: locationId, issue_quantity: locationId ? String(defaultIssue) : "0" });
  }

  const linesPayload: ApprovePartRequestLineInput[] = request.lines.map((line) => {
    const state = lineState[line.id];
    const issueQuantity = Number(state?.issue_quantity ?? "0") || 0;
    return {
      line_id: line.id,
      location_id: issueQuantity > 0 ? state?.location_id || null : null,
      issue_quantity: issueQuantity,
    };
  });

  const hasInvalidLine = request.lines.some((line) => {
    const state = lineState[line.id];
    if (!state) return true;
    const issueQuantity = Number(state.issue_quantity);
    if (Number.isNaN(issueQuantity) || issueQuantity < 0) return true;
    if (issueQuantity > line.quantity) return true;
    if (issueQuantity > 0 && !state.location_id) return true;
    const locations = availableByLine.get(line.id) ?? [];
    const chosen = locations.find((entry) => entry.location_id === state.location_id);
    if (issueQuantity > 0 && (!chosen || issueQuantity > chosen.available)) return true;
    return false;
  });

  function handleApprove() {
    approve.mutate(
      { partRequestId: request!.id, input: { lines: linesPayload, note: note.trim() || null } },
      {
        onSuccess: () => {
          toast.success(t("maintenance.parts.approve.done"));
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("maintenance.parts.approve.title")}</DialogTitle>
          <DialogDescription>
            {t("maintenance.parts.approve.description").replace("{number}", request.job_number).replace("{machine}", request.equipment_name)}
          </DialogDescription>
        </DialogHeader>

        {availabilityLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : (
          <div className="space-y-4">
            <ul className="space-y-3">
              {request.lines.map((line) => {
                const state = lineState[line.id] ?? { location_id: "", issue_quantity: "0" };
                const locations = availableByLine.get(line.id) ?? [];
                const issueQuantity = Number(state.issue_quantity) || 0;
                const remainder = Math.max(0, line.quantity - issueQuantity);
                const chosenLocation = locations.find((entry) => entry.location_id === state.location_id);
                const overStock = issueQuantity > 0 && (!chosenLocation || issueQuantity > chosenLocation.available);
                return (
                  <li key={line.id} className="space-y-2 rounded-md border border-border p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                      <span className="min-w-0 break-words text-sm font-medium">{line.product_name}</span>
                      <span className="shrink-0 tabular-nums text-sm text-muted-foreground">
                        {t("maintenance.parts.approve.requested")}: {formatQuantity(line.quantity, line.uom_code)}
                      </span>
                    </div>
                    {locations.length === 0 ? (
                      <p className="text-xs text-muted-foreground">{t("maintenance.parts.approve.noStock")}</p>
                    ) : (
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        <div className="space-y-1">
                          <Label htmlFor={`approve-location-${line.id}`}>{t("maintenance.parts.approve.field.location")}</Label>
                          <Select
                            id={`approve-location-${line.id}`}
                            value={state.location_id}
                            onChange={(event) => handleLocationChange(line.id, event.target.value, line.quantity)}
                          >
                            <option value="">{t("maintenance.parts.approve.field.location.none")}</option>
                            {locations.map((location) => (
                              <option key={location.location_id} value={location.location_id}>
                                {location.location_name} — {formatQuantity(location.available, line.uom_code)} {t("maintenance.parts.approve.field.location.available")}
                              </option>
                            ))}
                          </Select>
                        </div>
                        <div className="space-y-1">
                          <Label htmlFor={`approve-quantity-${line.id}`}>{t("maintenance.parts.approve.field.issueQuantity")}</Label>
                          <Input
                            id={`approve-quantity-${line.id}`}
                            type="number"
                            min={0}
                            max={Math.min(line.quantity, chosenLocation?.available ?? line.quantity)}
                            step="any"
                            value={state.issue_quantity}
                            onChange={(event) => updateLine(line.id, { issue_quantity: event.target.value })}
                            error={overStock ? t("maintenance.parts.approve.error.insufficientStock") : undefined}
                          />
                        </div>
                      </div>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {t("maintenance.parts.approve.toOrder")}: <span className="font-medium text-foreground">{formatQuantity(remainder, line.uom_code)}</span>
                    </p>
                  </li>
                );
              })}
            </ul>

            <div className="space-y-1.5">
              <Label htmlFor="approve-note">
                {t("maintenance.parts.approve.field.note")} <span className="font-normal text-muted-foreground">({t("common.optional")})</span>
              </Label>
              <textarea id="approve-note" rows={2} className={TEXTAREA_CLASS} value={note} onChange={(event) => setNote(event.target.value)} />
            </div>

            {approve.isError && (
              <p className="text-sm text-destructive" role="alert">
                {apiErrorMessage(approve.error, t("maintenance.parts.approve.error"))}
              </p>
            )}

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="button" onClick={handleApprove} disabled={hasInvalidLine || approve.isPending}>
                {approve.isPending ? t("maintenance.parts.approve.saving") : t("maintenance.parts.approve.submit")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
