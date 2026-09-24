import { ShiftValidationPanel } from "./shift/ShiftValidationPanel";
import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ClipboardCheck, Inbox, Pencil, XCircle } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { BulkActionBar } from "../../components/patterns/BulkActionBar";
import { useSelection } from "../../lib/useSelection";
import AllClearIllustration from "../../assets/illustrations/empty-states/empty-all-clear.svg?react";
import { listProducts, listWorkOrders } from "./api";
import {
  adminUpdateQualityReport,
  listQualityReports,
  raiseNonConformity,
  rejectQualityReport,
  getQualityReport,
  validateQualityReport,
  type ConformityLine,
  type QualityReport,
} from "../qc/api";

import { formatQuantity, productUnit } from "../../lib/units";
import { listLocations, listUoms } from "../warehouse/api";
import { AppLoader } from "../../components/patterns/AppLoader";
const QUALITY_QUERY_KEY = ["qc", "quality-reports", "pending"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

interface PendingItem {
  id: string;
  reportDate: string;
  team: string | null;
  shift: string | null;
  submittedAt: string | null;
}

export function ValidationCenterTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reviewing, setReviewing] = useState<PendingItem | null>(null);

  const { data: qualityReports = [], isLoading } = useQuery({
    queryKey: QUALITY_QUERY_KEY,
    queryFn: () => listQualityReports(token, { status: "submitted" }),
  });
  const { data: workOrders = [] } = useQuery({
    queryKey: WORK_ORDERS_QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });

  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;

  const items: PendingItem[] = qualityReports
    .map((r: QualityReport) => ({
      id: r.id,
      reportDate: r.report_date,
      team: r.team,
      shift: r.shift,
      submittedAt: r.submitted_at,
    }))
    .sort((a, b) => (a.submittedAt ?? "").localeCompare(b.submittedAt ?? ""));

  // One card per day, that day's pending shift reports nested underneath. A QC
  // report follows a shift, and a shift can pack several OFs, so there is no
  // single work order to group under -- the OFs show per line in the review.
  const grouped = Array.from(
    items.reduce((map, item) => {
      const bucket = map.get(item.reportDate) ?? [];
      bucket.push(item);
      return map.set(item.reportDate, bucket);
    }, new Map<string, PendingItem[]>()),
  )
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([reportDate, groupItems]) => ({ reportDate, items: groupItems }));

  function invalidateEverything() {
    for (const key of [
      QUALITY_QUERY_KEY,
      ["qc", "quality-reports"],
      ["qc", "follow-ups"],
      ["warehouse", "stock"],
      ["warehouse", "stock", "moves"],
    ]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  }

  const selection = useSelection(items.map((item) => item.id));
  const [bulkValidateOpen, setBulkValidateOpen] = useState(false);
  const [bulkRejectOpen, setBulkRejectOpen] = useState(false);
  const [bulkRejectReason, setBulkRejectReason] = useState("");
  const selectedItems = items.filter((item) => selection.isSelected(item.id));

  const bulkValidateMutation = useMutation({
    mutationFn: async () => {
      const settled = await Promise.allSettled(
        selectedItems.map((item) => validateQualityReport(token, item.id, crypto.randomUUID())),
      );
      return { succeeded: settled.filter((r) => r.status === "fulfilled").length, total: settled.length };
    },
    onSuccess: ({ succeeded, total }) => {
      invalidateEverything();
      const failed = total - succeeded;
      if (succeeded > 0) toast.success(`${succeeded} ${t("production.validation.bulkValidateSucceeded")}`);
      if (failed > 0) toast.error(`${failed} ${t("production.validation.bulkValidateFailed")}`);
      setBulkValidateOpen(false);
      selection.clear();
    },
  });

  const bulkRejectMutation = useMutation({
    mutationFn: async (reason: string) => {
      const settled = await Promise.allSettled(
        selectedItems.map((item) => rejectQualityReport(token, item.id, reason)),
      );
      return { succeeded: settled.filter((r) => r.status === "fulfilled").length, total: settled.length };
    },
    onSuccess: ({ succeeded, total }) => {
      invalidateEverything();
      const failed = total - succeeded;
      if (succeeded > 0) toast.success(`${succeeded} ${t("production.validation.bulkRejectSucceeded")}`);
      if (failed > 0) toast.error(`${failed} ${t("production.validation.bulkRejectFailed")}`);
      setBulkRejectOpen(false);
      setBulkRejectReason("");
      selection.clear();
    },
  });

  return (
    <div className="space-y-6">
      <ShiftValidationPanel />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-1">
        <StatCard
          label={t("production.validation.stat.quality")}
          value={items.length}
          icon={<ClipboardCheck className="h-5 w-5" />}
          accent="accent"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("production.validation.title")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("production.validation.subtitle")}</p>
        </CardHeader>
        <CardContent className={grouped.length === 0 ? "p-0" : "space-y-3"}>
          {!isLoading && items.length > 0 && (
            <BulkActionBar count={selection.count} onClear={selection.clear}>
              <Dialog open={bulkValidateOpen} onOpenChange={setBulkValidateOpen}>
                <DialogTrigger asChild>
                  <Button size="sm">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    {t("production.validation.bulkValidate")}
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t("production.validation.dialog.bulkValidate.title")}</DialogTitle>
                    <DialogDescription>{t("production.validation.dialog.bulkValidate.description")}</DialogDescription>
                  </DialogHeader>
                  <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                    {selectedItems.map((item) => (
                      <div key={item.id} className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium">{item.reportDate}</span>
                        <span className="text-muted-foreground">
                          {t("production.validation.source.quality")}
                          {item.shift ? ` · ${item.shift}` : ""}
                          {item.team ? ` · ${item.team}` : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                  <Button className="w-full" onClick={() => bulkValidateMutation.mutate()} disabled={bulkValidateMutation.isPending}>
                    {bulkValidateMutation.isPending ? t("production.validation.bulkValidating") : t("production.validation.bulkValidate")}
                  </Button>
                </DialogContent>
              </Dialog>
              <Dialog
                open={bulkRejectOpen}
                onOpenChange={(open) => {
                  setBulkRejectOpen(open);
                  if (open) setBulkRejectReason("");
                }}
              >
                <DialogTrigger asChild>
                  <Button size="sm" variant="outline">
                    <XCircle className="h-3.5 w-3.5" />
                    {t("production.validation.bulkReject")}
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t("production.validation.dialog.bulkReject.title")}</DialogTitle>
                    <DialogDescription>{t("production.validation.dialog.bulkReject.description")}</DialogDescription>
                  </DialogHeader>
                  <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                    {selectedItems.map((item) => (
                      <div key={item.id} className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium">{item.reportDate}</span>
                        <span className="text-muted-foreground">
                          {t("production.validation.source.quality")}
                          {item.shift ? ` · ${item.shift}` : ""}
                          {item.team ? ` · ${item.team}` : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="bulk_rejection_reason">{t("production.validation.field.rejectionReason")}</Label>
                    <Input
                      id="bulk_rejection_reason"
                      value={bulkRejectReason}
                      onChange={(e) => setBulkRejectReason(e.target.value)}
                      placeholder={t("production.validation.field.rejectionPlaceholder")}
                    />
                  </div>
                  <Button
                    className="w-full"
                    variant="outline"
                    onClick={() => bulkRejectMutation.mutate(bulkRejectReason)}
                    disabled={bulkRejectMutation.isPending || !bulkRejectReason.trim()}
                  >
                    {bulkRejectMutation.isPending ? t("production.validation.bulkRejecting") : t("production.validation.bulkReject")}
                  </Button>
                </DialogContent>
              </Dialog>
            </BulkActionBar>
          )}
          {isLoading ? (
            <AppLoader className="py-8" />
          ) : grouped.length === 0 ? (
            <EmptyState
              icon={<Inbox className="h-5 w-5" />}
              illustration={<AllClearIllustration className="h-44 w-56" />}
              title={t("production.validation.empty.title")}
              description={t("production.validation.empty.description")}
            />
          ) : (
            <AnimatePresence initial={false}>
              {grouped.map((group) => (
                <motion.div
                  key={group.reportDate}
                  layout
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="overflow-hidden rounded-lg border border-border"
                >
                  <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/40 px-4 py-2.5">
                    <span className="font-medium">{group.reportDate}</span>
                    <Badge variant="outline" className="ml-auto">
                      {group.items.length} {t("production.validation.pending")}
                    </Badge>
                  </div>
                  <div className="divide-y divide-border">
                    {group.items.map((item) => (
                      <div
                        key={item.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => setReviewing(item)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setReviewing(item);
                          }
                        }}
                        className="flex w-full cursor-pointer items-center gap-4 p-3 text-left transition-colors hover:bg-muted/40"
                      >
                        <div onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={selection.isSelected(item.id)}
                            onCheckedChange={() => selection.toggle(item.id)}
                            aria-label={t("production.validation.review")}
                          />
                        </div>
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
                          <ClipboardCheck className="h-4 w-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline">{t("production.validation.source.quality")}</Badge>
                            <span className="text-sm text-muted-foreground">
                              {[item.shift, item.team].filter(Boolean).join(" · ") || item.reportDate}
                            </span>
                          </div>
                        </div>
                        <span className="text-sm text-muted-foreground">{t("production.validation.review")}</span>
                      </div>
                    ))}
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </CardContent>
      </Card>

      {reviewing && (
        <ReviewDialog
          item={reviewing}
          referenceOf={referenceOf}
          onClose={() => setReviewing(null)}
          onDone={() => {
            invalidateEverything();
            setReviewing(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * The quality-report review panel. Loads the report's conformity lines on
 * demand so a validator sees what they are approving -- one line per product
 * and OF the shift packed -- then validates or rejects it.
 */
function ReviewDialog({
  item,
  referenceOf,
  onClose,
  onDone,
}: {
  item: PendingItem;
  referenceOf: (ofId: string) => string;
  onClose: () => void;
  onDone: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [rejectionReason, setRejectionReason] = useState("");
  const [editingQuality, setEditingQuality] = useState(false);
  // Keyed by conformity line id.
  const [qualityEdit, setQualityEdit] = useState<Record<string, LineEdit>>({});
  const [qualityEditReason, setQualityEditReason] = useState("");
  const [raiseNc, setRaiseNc] = useState(true);
  const [ncSourceLocationId, setNcSourceLocationId] = useState("");
  const [ncQuarantineLocationId, setNcQuarantineLocationId] = useState("");
  const [ncDefectType, setNcDefectType] = useState("");

  const { data: qualityDetail } = useQuery({
    queryKey: ["qc", "quality-reports", item.id],
    queryFn: () => getQualityReport(token, item.id),
  });
  const { data: locations = [] } = useQuery({
    queryKey: LOCATIONS_QUERY_KEY,
    queryFn: () => listLocations(token),
  });
  // Needed to raise an NC: resolving each line's product packets_per_carton
  // converts the report's carton count into the piece count the product is
  // actually stocked and moved in.
  const { data: products = [] } = useQuery({
    queryKey: ["core", "products"],
    queryFn: () => listProducts(token),
  });
  const { data: uoms = [] } = useQuery({
    queryKey: ["core", "uoms"],
    queryFn: () => listUoms(token),
  });

  const lines = qualityDetail?.lines ?? [];
  const packetsPerCartonOf = (productId: string) => {
    const product = products.find((p) => p.id === productId);
    return product?.packets_per_carton && product.packets_per_carton > 0 ? product.packets_per_carton : null;
  };
  const lineLabel = (line: ConformityLine) =>
    `${products.find((p) => p.id === line.product_id)?.name ?? line.product_id} · ${referenceOf(line.of_id)}`;

  // One case per (OF, product): a shift can pack the same product for the same
  // OF on several rows, and one NC covers them all -- the backend derives its
  // quantity from the sum of those lines, so the figure shown is the group's sum.
  const defectiveLines = lines.filter((line) => Number(line.non_conforming_cartons) > 0);
  const defectiveGroups = Object.values(
    defectiveLines.reduce<Record<string, typeof defectiveLines[number]>>((groups, line) => {
      const key = `${line.of_id}:${line.product_id}`;
      const group = groups[key];
      groups[key] = group
        ? {
            ...group,
            non_conforming_cartons: Number(group.non_conforming_cartons) + Number(line.non_conforming_cartons),
            defect_details: [group.defect_details, line.defect_details].filter(Boolean).join(" / ") || null,
          }
        : line;
      return groups;
    }, {}),
  );
  const canRaiseNc = defectiveGroups.length > 0;
  const ncPlan = defectiveGroups.map((line) => {
    const perCarton = packetsPerCartonOf(line.product_id);
    const cartons = Number(line.non_conforming_cartons);
    return {
      line,
      perCarton,
      cartons,
      quantity: perCarton ? cartons * perCarton : cartons,
      unit: productUnit(line.product_id, products, uoms),
    };
  });

  // Pre-fill the defect type only when there is exactly one case to raise --
  // with several, each NC falls back to its own group's defect details instead.
  const singleDefect = defectiveGroups.length === 1 ? defectiveGroups[0].defect_details : null;
  useEffect(() => {
    if (singleDefect && !ncDefectType) setNcDefectType(singleDefect);
  }, [singleDefect, ncDefectType]);

  const validateMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      await validateQualityReport(token, item.id, crypto.randomUUID());
    },
    onSuccess: () => {
      toast.success(t("production.validation.validated"));
      onDone();
    },
    onError: (error) => {
      toast.error(t("production.validation.validateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      await rejectQualityReport(token, item.id, rejectionReason);

      // One NC per non-conforming (OF, product), all moved between the same two locations.
      if (canRaiseNc && raiseNc && ncSourceLocationId && ncQuarantineLocationId) {
        const settled = await Promise.allSettled(
          ncPlan.map((entry) =>
            raiseNonConformity(token, {
              of_id: entry.line.of_id,
              product_id: entry.line.product_id,
              quantity: entry.quantity,
              source_location_id: ncSourceLocationId,
              quarantine_location_id: ncQuarantineLocationId,
              defect_type: ncDefectType.trim() || entry.line.defect_details || "Non-conformity detected",
              severity: "minor",
              quality_report_id: item.id,
              description: entry.line.defect_details || undefined,
              correlation_id: crypto.randomUUID(),
            }),
          ),
        );
        const failure = settled.find((r): r is PromiseRejectedResult => r.status === "rejected");
        if (failure) {
          // Rejection succeeded, but an NC failed — show warning but still finish
          const errorMessage = failure.reason instanceof ApiError ? failure.reason.message : String(failure.reason);
          toast.warning(t("production.validation.nc.partialError").replace("{message}", errorMessage));
          queryClient.invalidateQueries({ queryKey: QUALITY_QUERY_KEY });
          queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
          queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
          onDone();
          return;
        }
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUALITY_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
      toast.success(t("production.validation.rejected"));
      onDone();
    },
    onError: (error) => {
      toast.error(t("production.validation.rejectError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  // A correction here goes through the same admin edit-in-place endpoint as the
  // Quality Reports list, just surfaced where a validator is already looking:
  // at the declared figures, mid-examination, before deciding to validate.
  function openQualityEdit() {
    setQualityEdit(
      Object.fromEntries(
        lines.map((line) => [
          line.id,
          {
            conforming_cartons: String(line.conforming_cartons ?? 0),
            non_conforming_cartons: String(line.non_conforming_cartons ?? 0),
            defect_details: line.defect_details ?? "",
          },
        ]),
      ),
    );
    setQualityEditReason("");
    setEditingQuality(true);
  }

  const updateQualityMutation = useMutation({
    // Lines are matched by packing row server-side; the report's comments and
    // corrective action are not sent, so they stay as they are.
    mutationFn: () =>
      adminUpdateQualityReport(token, item.id, {
        lines: lines.map((line) => {
          const edit = qualityEdit[line.id];
          return {
            shift_packing_row_id: line.shift_packing_row_id,
            conforming_cartons: Number(edit?.conforming_cartons) || 0,
            non_conforming_cartons: Number(edit?.non_conforming_cartons) || 0,
            defect_details: edit?.defect_details || null,
          };
        }),
        reason: qualityEditReason,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["qc", "quality-reports", item.id] });
      queryClient.invalidateQueries({ queryKey: QUALITY_QUERY_KEY });
      toast.success(t("production.reports.updated"));
      setEditingQuality(false);
    },
    onError: (error) => {
      toast.error(t("production.reports.updateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const figures = qualityFigures(lines, (line) => !packetsPerCartonOf(line.product_id), lineLabel);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {item.reportDate} · {t("production.validation.source.quality")}
          </DialogTitle>
          <DialogDescription>
            {[item.shift, item.team].filter(Boolean).join(" · ") || item.reportDate}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border border-border">
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("production.validation.figures")}
              </p>
              {!editingQuality && (
                <Button size="sm" variant="ghost" onClick={openQualityEdit} disabled={!qualityDetail || lines.length === 0}>
                  <Pencil className="h-3.5 w-3.5" />
                  {t("common.edit")}
                </Button>
              )}
            </div>
            {editingQuality ? (
              <div className="space-y-3 px-4 py-3">
                {lines.map((line) => {
                  const isSac = !packetsPerCartonOf(line.product_id);
                  const edit = qualityEdit[line.id] ?? { conforming_cartons: "", non_conforming_cartons: "", defect_details: "" };
                  const setField = (field: keyof LineEdit, value: string) =>
                    setQualityEdit((s) => ({ ...s, [line.id]: { ...edit, [field]: value } }));
                  return (
                    <div key={line.id} className="space-y-2 rounded-md border border-border p-3">
                      <p className="text-sm font-medium">{lineLabel(line)}</p>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <div className="space-y-1.5">
                          <Label htmlFor={`q_edit_conforming_${line.id}`}>
                            {t(isSac ? "qc.quality.field.conformingSacs" : "qc.quality.field.conforming")} (
                            {t(isSac ? "qc.quality.unit.sacs" : "qc.quality.unit.cartons")})
                          </Label>
                          <Input
                            id={`q_edit_conforming_${line.id}`}
                            type="number"
                            step="1"
                            value={edit.conforming_cartons}
                            onChange={(e) => setField("conforming_cartons", e.target.value)}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor={`q_edit_non_conforming_${line.id}`}>
                            {t(isSac ? "qc.quality.field.nonConformingSacs" : "qc.quality.field.nonConforming")} (
                            {t(isSac ? "qc.quality.unit.sacs" : "qc.quality.unit.cartons")})
                          </Label>
                          <Input
                            id={`q_edit_non_conforming_${line.id}`}
                            type="number"
                            step="1"
                            value={edit.non_conforming_cartons}
                            onChange={(e) => setField("non_conforming_cartons", e.target.value)}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor={`q_edit_defects_${line.id}`}>{t("qc.quality.field.defectDetails")}</Label>
                          <Input
                            id={`q_edit_defects_${line.id}`}
                            value={edit.defect_details}
                            onChange={(e) => setField("defect_details", e.target.value)}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
                <div className="space-y-1.5">
                  <Label htmlFor="q_edit_reason">{t("production.reports.correctionReason")}</Label>
                  <Input
                    id="q_edit_reason"
                    value={qualityEditReason}
                    onChange={(e) => setQualityEditReason(e.target.value)}
                    placeholder={t("production.reports.correctionReasonPlaceholder")}
                  />
                  <p className="text-xs text-muted-foreground">{t("production.reports.correctionHelp")}</p>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    onClick={() => updateQualityMutation.mutate()}
                    disabled={updateQualityMutation.isPending || !qualityEditReason.trim()}
                  >
                    {updateQualityMutation.isPending ? t("common.saving") : t("common.save")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1"
                    onClick={() => setEditingQuality(false)}
                  >
                    {t("common.cancel")}
                  </Button>
                </div>
              </div>
            ) : figures.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">{t("common.none")}</p>
            ) : (
              <dl className="grid grid-cols-1 gap-x-6 gap-y-2 px-4 py-3 sm:grid-cols-2">
                {figures.map((f, index) => (
                  <div key={`${f.label}:${index}`} className="flex items-baseline justify-between gap-3">
                    <dt className="text-sm text-muted-foreground">
                      {f.labelText ?? t(f.label as Parameters<typeof t>[0])}
                      {f.suffix ? ` — ${f.suffix}` : ""}
                    </dt>
                    <dd className="text-sm font-medium tabular-nums">
                      {typeof f.value === "string" ? f.value : formatQuantity(f.value, f.unit)}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="rejection">{t("production.validation.field.rejectionReason")}</Label>
            <Input
              id="rejection"
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder={t("production.validation.field.rejectionPlaceholder")}
            />
          </div>

          {canRaiseNc && (
            <div className="space-y-3 rounded-lg border border-border p-3 bg-muted/30">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="nc_create"
                  checked={raiseNc}
                  onChange={(e) => setRaiseNc(e.target.checked)}
                  className="h-4 w-4 rounded border border-border"
                />
                <Label htmlFor="nc_create" className="text-sm font-medium cursor-pointer">
                  {t("production.validation.nc.create")}
                </Label>
              </div>

              {raiseNc && (
                <div className="space-y-3">
                  {ncPlan.map((entry) => (
                    <div key={`${entry.line.of_id}:${entry.line.product_id}`} className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">{t("production.validation.nc.field.product")}</p>
                        <p className="font-medium">{lineLabel(entry.line)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">{t("production.validation.nc.field.quantity")}</p>
                        <p className="font-medium">{formatQuantity(entry.quantity, entry.unit)}</p>
                        {entry.perCarton && (
                          <p className="text-xs text-muted-foreground">
                            {t("production.validation.nc.field.cartonBreakdown")
                              .replace("{cartons}", String(entry.cartons))
                              .replace("{perCarton}", String(entry.perCarton))}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}

                  <div className="space-y-1.5">
                    <Label htmlFor="nc_defect_type">{t("production.validation.nc.field.defectType")}</Label>
                    <Input
                      id="nc_defect_type"
                      value={ncDefectType}
                      onChange={(e) => setNcDefectType(e.target.value)}
                      placeholder="Packaging defect, contamination, etc."
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="nc_source_location">{t("production.validation.nc.field.sourceLocation")}</Label>
                    <Select value={ncSourceLocationId} onChange={(e) => setNcSourceLocationId(e.target.value)}>
                      <option value="">— Choose a location —</option>
                      {locations.map((loc) => (
                        <option key={loc.id} value={loc.id}>
                          {loc.name}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="nc_quarantine_location">{t("production.validation.nc.field.quarantineLocation")}</Label>
                    <Select value={ncQuarantineLocationId} onChange={(e) => setNcQuarantineLocationId(e.target.value)}>
                      <option value="">— Choose a location —</option>
                      {locations.map((loc) => (
                        <option key={loc.id} value={loc.id}>
                          {loc.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex gap-2">
            <Button
              className="flex-1"
              onClick={() => validateMutation.mutate()}
              disabled={validateMutation.isPending}
            >
              <CheckCircle2 className="h-4 w-4" />
              {validateMutation.isPending ? t("common.saving") : t("production.validation.validate")}
            </Button>
            <Button
              className="flex-1"
              variant="outline"
              onClick={() => rejectMutation.mutate()}
              disabled={
                rejectMutation.isPending ||
                !rejectionReason.trim() ||
                (canRaiseNc && raiseNc && (!ncSourceLocationId || !ncQuarantineLocationId))
              }
            >
              <XCircle className="h-4 w-4" />
              {rejectMutation.isPending ? t("common.saving") : t("production.validation.reject")}
            </Button>
          </div>

          <p className="text-xs text-muted-foreground">{t("production.validation.stockNote")}</p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface LineEdit {
  conforming_cartons: string;
  non_conforming_cartons: string;
  defect_details: string;
}

interface ReviewFigure {
  /** A translation key; `suffix` carries anything that is not translatable. */
  label: string;
  /** An already-readable name shown instead of translating `label`, for a name that has no key. */
  labelText?: string;
  /** Appended after the translated label: the line's product and OF. */
  suffix?: string;
  value: number | string | null;
  unit?: string | null;
}

/** Conforming / non-conforming / defect details, once per conformity line. */
function qualityFigures(
  lines: ConformityLine[],
  isSac: (line: ConformityLine) => boolean,
  lineLabel: (line: ConformityLine) => string,
): ReviewFigure[] {
  return lines.flatMap((line) => {
    const sac = isSac(line);
    const unit = sac ? "sacs" : "cartons";
    const suffix = lineLabel(line);
    return [
      { label: sac ? "qc.quality.field.conformingSacs" : "qc.quality.field.conforming", suffix, value: line.conforming_cartons, unit },
      { label: sac ? "qc.quality.field.nonConformingSacs" : "qc.quality.field.nonConforming", suffix, value: line.non_conforming_cartons, unit },
      { label: "qc.quality.field.defectDetails", suffix, value: line.defect_details ?? "—" },
    ];
  });
}
