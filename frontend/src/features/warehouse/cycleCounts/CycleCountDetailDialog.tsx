import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Badge } from "../../../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { useProductCatalog } from "../../products/catalog";
import { listLocations } from "../api";
import {
  cancelCycleCount,
  completeCycleCount,
  cycleCountQueryKey,
  getCycleCount,
  resolveCycleCountLine,
  startCycleCount,
  submitCycleCountLine,
  CYCLE_COUNTS_QUERY_KEY,
  type CycleCountLine,
} from "./api";

function LineRow({
  line,
  productName,
  locationName,
  countInProgress,
  cycleCountId,
}: {
  line: CycleCountLine;
  productName: string;
  locationName: string;
  countInProgress: boolean;
  cycleCountId: string;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");

  const submitMutation = useMutation({
    mutationFn: () => submitCycleCountLine(token, cycleCountId, line.id, Number(draft)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: cycleCountQueryKey(cycleCountId) }),
  });
  const resolveMutation = useMutation({
    mutationFn: (decision: "approve" | "reject") => resolveCycleCountLine(token, cycleCountId, line.id, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: cycleCountQueryKey(cycleCountId) });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
    },
  });

  const variance = line.counted_quantity !== null && line.expected_quantity !== null ? line.counted_quantity - line.expected_quantity : null;
  const needsDecision = line.status === "counted" && line.resolution === null;

  return (
    <TableRow>
      <TableCell>{productName}</TableCell>
      <TableCell className="text-muted-foreground">{locationName}</TableCell>
      <TableCell>{line.expected_quantity ?? t("warehouse.cycleCounts.line.masked")}</TableCell>
      <TableCell>
        {line.status === "pending" && countInProgress ? (
          <div className="flex items-center gap-1.5">
            <Input
              type="number"
              step="any"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="h-8 w-24"
            />
            <Button size="sm" onClick={() => submitMutation.mutate()} disabled={draft === "" || submitMutation.isPending}>
              {t("warehouse.cycleCounts.line.submit")}
            </Button>
          </div>
        ) : (
          (line.counted_quantity ?? "—")
        )}
      </TableCell>
      <TableCell>{variance !== null ? (variance > 0 ? `+${variance}` : variance) : "—"}</TableCell>
      <TableCell>
        {line.resolution === "matched" && <Badge variant="success">{t("warehouse.cycleCounts.resolution.matched")}</Badge>}
        {line.resolution === "approved" && <Badge variant="success">{t("warehouse.cycleCounts.resolution.approved")}</Badge>}
        {line.resolution === "rejected" && <Badge variant="outline">{t("warehouse.cycleCounts.resolution.rejected")}</Badge>}
        {needsDecision && (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={() => resolveMutation.mutate("approve")} disabled={resolveMutation.isPending}>
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
              {t("warehouse.cycleCounts.line.approve")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => resolveMutation.mutate("reject")} disabled={resolveMutation.isPending}>
              <XCircle className="h-3.5 w-3.5 text-destructive" />
              {t("warehouse.cycleCounts.line.reject")}
            </Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

export function CycleCountDetailDialog({
  open,
  onOpenChange,
  cycleCountId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cycleCountId: string | null;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const { data: detail } = useQuery({
    queryKey: cycleCountId ? cycleCountQueryKey(cycleCountId) : ["warehouse", "cycleCounts", "none"],
    queryFn: () => getCycleCount(token, cycleCountId!),
    enabled: open && cycleCountId !== null,
  });

  const invalidateAfterAction = () => {
    queryClient.invalidateQueries({ queryKey: CYCLE_COUNTS_QUERY_KEY });
    if (cycleCountId) queryClient.invalidateQueries({ queryKey: cycleCountQueryKey(cycleCountId) });
  };
  const startMutation = useMutation({
    mutationFn: () => startCycleCount(token, cycleCountId!),
    onSuccess: invalidateAfterAction,
  });
  const completeMutation = useMutation({
    mutationFn: () => completeCycleCount(token, cycleCountId!),
    onSuccess: () => {
      invalidateAfterAction();
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelCycleCount(token, cycleCountId!),
    onSuccess: invalidateAfterAction,
  });

  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;
  const locationName = (locationId: string) => locations.find((l) => l.id === locationId)?.name ?? locationId;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("warehouse.cycleCounts.detail.title")}</DialogTitle>
          {detail && (
            <DialogDescription>
              {t(`warehouse.cycleCounts.status.${detail.status}`)} · {t(`warehouse.cycleCounts.type.${detail.count_type}`)}
            </DialogDescription>
          )}
        </DialogHeader>

        {detail && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {detail.status === "draft" && (
                <Button size="sm" onClick={() => startMutation.mutate()} disabled={startMutation.isPending}>
                  {t("warehouse.cycleCounts.action.start")}
                </Button>
              )}
              {detail.status === "in_progress" && (
                <Button size="sm" onClick={() => completeMutation.mutate()} disabled={completeMutation.isPending}>
                  {t("warehouse.cycleCounts.action.complete")}
                </Button>
              )}
              {(detail.status === "draft" || detail.status === "in_progress") && (
                <Button variant="outline" size="sm" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>
                  {t("warehouse.cycleCounts.action.cancel")}
                </Button>
              )}
            </div>
            {completeMutation.isError && (
              <p className="text-sm text-destructive">
                {completeMutation.error instanceof ApiError ? completeMutation.error.message : t("warehouse.cycleCounts.dialog.error")}
              </p>
            )}

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("warehouse.cycleCounts.column.product")}</TableHead>
                  <TableHead>{t("warehouse.cycleCounts.column.location")}</TableHead>
                  <TableHead>{t("warehouse.cycleCounts.column.expected")}</TableHead>
                  <TableHead>{t("warehouse.cycleCounts.column.counted")}</TableHead>
                  <TableHead>{t("warehouse.cycleCounts.column.variance")}</TableHead>
                  <TableHead>{t("warehouse.cycleCounts.column.resolution")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.lines.map((line) => (
                  <LineRow
                    key={line.id}
                    line={line}
                    productName={productName(line.product_id)}
                    locationName={locationName(line.location_id)}
                    countInProgress={detail.status === "in_progress"}
                    cycleCountId={detail.id}
                  />
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
