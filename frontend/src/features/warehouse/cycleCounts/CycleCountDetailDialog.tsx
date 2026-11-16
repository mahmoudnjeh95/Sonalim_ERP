import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Eye, NotebookPen, Printer, XCircle } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { useProductCatalog } from "../../products/catalog";
import { listLocations } from "../api";
import { DocumentAttachments } from "../DocumentAttachments";
import { openDocument } from "../printDocument";
import {
  addCycleCountFoundLine,
  cancelCycleCount,
  completeCycleCount,
  cycleCountQueryKey,
  getCycleCount,
  resolveCycleCountLine,
  startCycleCount,
  submitCycleCountLine,
  CYCLE_COUNTS_QUERY_KEY,
  type CycleCountDetail,
  type CycleCountLine,
} from "./api";

/** The locations a count covers: its whole site, or its scope location and everything under it. */
function locationsInScope<T extends { id: string; site_id: string; parent_location_id: string | null }>(all: T[], detail: CycleCountDetail): T[] {
  const inSite = all.filter((location) => location.site_id === detail.site_id);
  if (!detail.scope_location_id) return inSite;
  const covered = new Set([detail.scope_location_id]);
  for (let grew = true; grew; ) {
    grew = false;
    for (const location of inSite) {
      if (location.parent_location_id && covered.has(location.parent_location_id) && !covered.has(location.id)) {
        covered.add(location.id);
        grew = true;
      }
    }
  }
  return inSite.filter((location) => covered.has(location.id));
}

function AddFoundLine({
  cycleCountId,
  locations,
  products,
}: {
  cycleCountId: string;
  locations: { id: string; name: string }[];
  products: { id: string; name: string }[];
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [locationId, setLocationId] = useState("");
  const [productId, setProductId] = useState("");

  const mutation = useMutation({
    mutationFn: () => addCycleCountFoundLine(token, cycleCountId, { location_id: locationId, product_id: productId }),
    onSuccess: () => {
      setProductId("");
      queryClient.invalidateQueries({ queryKey: cycleCountQueryKey(cycleCountId) });
    },
  });

  return (
    <div className="space-y-1.5 rounded-md border p-3">
      <p className="text-sm font-medium">{t("warehouse.cycleCounts.found.title")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label={t("warehouse.cycleCounts.column.location")}
          className="h-8 w-auto"
          value={locationId}
          onChange={(event) => setLocationId(event.target.value)}
        >
          <option value="">{t("warehouse.cycleCounts.column.location")}</option>
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.name}
            </option>
          ))}
        </Select>
        <Select
          aria-label={t("warehouse.cycleCounts.column.product")}
          className="h-8 w-auto"
          value={productId}
          onChange={(event) => setProductId(event.target.value)}
        >
          <option value="">{t("warehouse.cycleCounts.column.product")}</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>
              {product.name}
            </option>
          ))}
        </Select>
        <Button size="sm" variant="outline" onClick={() => mutation.mutate()} disabled={!locationId || !productId || mutation.isPending}>
          {t("warehouse.cycleCounts.found.add")}
        </Button>
      </div>
      {mutation.isError && (
        <p className="text-sm text-destructive">
          {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.cycleCounts.dialog.error")}
        </p>
      )}
    </div>
  );
}

function LineRow({
  line,
  productName,
  locationName,
  countInProgress,
  cycleCountId,
  interim,
}: {
  line: CycleCountLine;
  productName: string;
  locationName: string;
  countInProgress: boolean;
  cycleCountId: string;
  interim: boolean;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [observation, setObservation] = useState("");

  const submitMutation = useMutation({
    mutationFn: () => submitCycleCountLine(token, cycleCountId, line.id, Number(draft)),
    onSuccess: () => {
      // A confirming count has to be typed afresh, not re-sent from what is left in the box.
      setDraft("");
      queryClient.invalidateQueries({ queryKey: cycleCountQueryKey(cycleCountId) });
    },
  });
  const resolveMutation = useMutation({
    mutationFn: (decision: "approve" | "reject" | "note") => resolveCycleCountLine(token, cycleCountId, line.id, decision, observation),
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
        {line.status === "pending" && line.counts_recorded > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">
            {t(line.counts_recorded === 1 ? "warehouse.cycleCounts.line.secondCount" : "warehouse.cycleCounts.line.thirdCount")}
          </p>
        )}
      </TableCell>
      <TableCell>{variance !== null ? (variance > 0 ? `+${variance}` : variance) : "—"}</TableCell>
      <TableCell>
        {line.resolution === "matched" && <Badge variant="success">{t("warehouse.cycleCounts.resolution.matched")}</Badge>}
        {line.resolution === "approved" && <Badge variant="success">{t("warehouse.cycleCounts.resolution.approved")}</Badge>}
        {line.resolution === "rejected" && <Badge variant="outline">{t("warehouse.cycleCounts.resolution.rejected")}</Badge>}
        {line.resolution === "noted" && <Badge variant="outline">{t("warehouse.cycleCounts.resolution.noted")}</Badge>}
        {line.observation && <p className="mt-1 text-xs text-muted-foreground">{line.observation}</p>}
        {needsDecision && (
          <div className="space-y-1">
            <Input
              aria-label={t("warehouse.cycleCounts.column.observation")}
              placeholder={t("warehouse.cycleCounts.column.observation")}
              value={observation}
              onChange={(event) => setObservation(event.target.value)}
              className="h-8"
            />
            <div className="flex items-center gap-1">
              {interim ? (
                <Button variant="ghost" size="sm" onClick={() => resolveMutation.mutate("note")} disabled={resolveMutation.isPending || !observation.trim()}>
                  <NotebookPen className="h-3.5 w-3.5" />
                  {t("warehouse.cycleCounts.line.note")}
                </Button>
              ) : (
                <>
                  <Button variant="ghost" size="sm" onClick={() => resolveMutation.mutate("approve")} disabled={resolveMutation.isPending || !observation.trim()}>
                    <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                    {t("warehouse.cycleCounts.line.approve")}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => resolveMutation.mutate("reject")} disabled={resolveMutation.isPending || !observation.trim()}>
                    <XCircle className="h-3.5 w-3.5 text-destructive" />
                    {t("warehouse.cycleCounts.line.reject")}
                  </Button>
                </>
              )}
            </div>
            {resolveMutation.isError && (
              <p className="text-xs text-destructive">
                {resolveMutation.error instanceof ApiError ? resolveMutation.error.message : t("warehouse.cycleCounts.dialog.error")}
              </p>
            )}
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
  const { session, hasPermission } = useAuth();
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

  const headerFields = (current: CycleCountDetail): [string, string][] => [
    [t("warehouse.cycleCounts.field.mode"), t(`warehouse.cycleCounts.mode.${current.mode}`)],
    [t("warehouse.cycleCounts.field.scope"), current.scope_location_id ? locationName(current.scope_location_id) : t("warehouse.cycleCounts.field.scope.wholeSite")],
    [t("warehouse.cycleCounts.field.countType"), t(`warehouse.cycleCounts.type.${current.count_type}`)],
    [t("voucher.date"), String(current.started_at ?? current.created_at).slice(0, 10)],
  ];
  const documentTitle = (current: CycleCountDetail) => `${t(`warehouse.cycleCounts.mode.${current.mode}`)} ${current.number ?? ""}`;
  // The manual's blank report: products and book quantities, count and observation columns empty. A blind
  // count's sheet leaves the book quantity out too, or the counter would carry it to the shelf.
  const blankSheet = (current: CycleCountDetail) => {
    const showBooks = current.count_type !== "blind";
    openDocument(
      {
        title: documentTitle(current),
        fields: headerFields(current),
        headers: [
          t("warehouse.cycleCounts.column.product"),
          t("warehouse.cycleCounts.column.location"),
          ...(showBooks ? [t("warehouse.cycleCounts.column.expected")] : []),
          t("warehouse.cycleCounts.column.count1"),
          t("warehouse.cycleCounts.column.count2"),
          t("warehouse.cycleCounts.column.count3"),
          t("warehouse.cycleCounts.column.observation"),
        ],
        rows: current.lines.map((line) => [
          productName(line.product_id),
          locationName(line.location_id),
          ...(showBooks ? [line.expected_quantity ?? ""] : []),
          "",
          "",
          "",
          "",
        ]),
      },
      { print: false },
    );
  };
  const printCount = (current: CycleCountDetail, print: boolean) => {
    const dash = (value: number | null) => value ?? "—";
    openDocument(
      {
        title: documentTitle(current),
        fields: headerFields(current),
        headers: [
          t("warehouse.cycleCounts.column.product"),
          t("warehouse.cycleCounts.column.location"),
          t("warehouse.cycleCounts.column.expected"),
          t("warehouse.cycleCounts.column.count1"),
          t("warehouse.cycleCounts.column.count2"),
          t("warehouse.cycleCounts.column.count3"),
          t("warehouse.cycleCounts.column.variance"),
          t("warehouse.cycleCounts.column.observation"),
        ],
        rows: current.lines.map((line) => [
          productName(line.product_id),
          locationName(line.location_id),
          dash(line.expected_quantity),
          dash(line.count_1),
          dash(line.count_2),
          dash(line.count_3),
          line.counted_quantity !== null && line.expected_quantity !== null ? line.counted_quantity - line.expected_quantity : "—",
          line.observation ?? "",
        ]),
        footer: current.note ?? undefined,
      },
      { print },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("warehouse.cycleCounts.detail.title")}</DialogTitle>
          {detail && (
            <DialogDescription>
              {detail.number ? `${detail.number} · ` : ""}
              {t(`warehouse.cycleCounts.mode.${detail.mode}`)} · {t(`warehouse.cycleCounts.status.${detail.status}`)} · {t(`warehouse.cycleCounts.type.${detail.count_type}`)}
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
              {detail.lines.length > 0 && (
                <>
                  <Button variant="outline" size="sm" onClick={() => blankSheet(detail)}>
                    <ClipboardList className="h-3.5 w-3.5" />
                    {t("warehouse.cycleCounts.action.blankSheet")}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => printCount(detail, false)}>
                    <Eye className="h-3.5 w-3.5" />
                    {t("voucher.preview")}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => printCount(detail, true)}>
                    <Printer className="h-3.5 w-3.5" />
                    {t("voucher.print")}
                  </Button>
                </>
              )}
            </div>
            {detail.note && <p className="text-sm"><span className="font-medium">{t("voucher.note")} :</span> {detail.note}</p>}
            {detail.status === "draft" && <p className="text-sm text-muted-foreground">{t("warehouse.cycleCounts.detail.linesOnStart")}</p>}
            {startMutation.isError && (
              <p className="text-sm text-destructive">
                {startMutation.error instanceof ApiError ? startMutation.error.message : t("warehouse.cycleCounts.dialog.error")}
              </p>
            )}
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
                    interim={detail.mode === "interim"}
                  />
                ))}
              </TableBody>
            </Table>
            {detail.status === "in_progress" && hasPermission("warehouse.manage_cycle_counts") && (
              <AddFoundLine cycleCountId={detail.id} locations={locationsInScope(locations, detail)} products={products} />
            )}
            <DocumentAttachments entityType="cycle_count" entityId={detail.id} canManage={hasPermission("warehouse.manage_cycle_counts")} />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
