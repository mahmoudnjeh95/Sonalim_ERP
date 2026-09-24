import { ShiftValidationPanel } from "./shift/ShiftValidationPanel";
import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
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
  type QualityReport,
  type QualityReportDetail,
} from "../qc/api";

import { formatQuantity, productUnit } from "../../lib/units";
import { listLocations, listUoms } from "../warehouse/api";
import { AppLoader } from "../../components/patterns/AppLoader";
const QUALITY_QUERY_KEY = ["qc", "quality-reports", "pending"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

interface PendingItem {
  id: string;
  ofId: string;
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
      ofId: r.of_id,
      reportDate: r.report_date,
      team: r.team,
      shift: r.shift,
      submittedAt: r.submitted_at,
    }))
    .sort((a, b) => (a.submittedAt ?? "").localeCompare(b.submittedAt ?? ""));

  // One card per work order, its pending reports nested underneath — a validator
  // reviews an order's shift, not a flat list of unrelated rows.
  const grouped = Array.from(
    items.reduce((map, item) => {
      const bucket = map.get(item.ofId) ?? [];
      bucket.push(item);
      return map.set(item.ofId, bucket);
    }, new Map<string, PendingItem[]>()),
  ).map(([ofId, groupItems]) => {
    const dates = groupItems.map((i) => i.reportDate).sort();
    const first = dates[0];
    const last = dates[dates.length - 1];
    return {
      ofId,
      reference: referenceOf(ofId),
      items: groupItems,
      dateRange: first === last ? first : `${first} → ${last}`,
    };
  });

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
                        <span className="font-medium">{referenceOf(item.ofId)}</span>
                        <span className="text-muted-foreground">
                          {t("production.validation.source.quality")} · {item.reportDate}
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
                        <span className="font-medium">{referenceOf(item.ofId)}</span>
                        <span className="text-muted-foreground">
                          {t("production.validation.source.quality")} · {item.reportDate}
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
                  key={group.ofId}
                  layout
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="overflow-hidden rounded-lg border border-border"
                >
                  <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/40 px-4 py-2.5">
                    <Link
                      to={`/production/work-orders/${group.ofId}`}
                      className="font-medium text-primary hover:underline"
                    >
                      {group.reference}
                    </Link>
                    <span className="text-sm text-muted-foreground">{group.dateRange}</span>
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
                              {item.reportDate}
                              {item.shift ? ` · ${item.shift}` : ""}
                              {item.team ? ` · ${item.team}` : ""}
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
          reference={referenceOf(reviewing.ofId)}
          ofProductId={workOrders.find((o) => o.id === reviewing.ofId)?.product_id ?? undefined}
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
 * The quality-report review panel. Loads the report's figures on demand so a
 * validator sees what they are approving, then validates or rejects it.
 */
function ReviewDialog({
  item,
  reference,
  ofProductId,
  onClose,
  onDone,
}: {
  item: PendingItem;
  reference: string;
  ofProductId: string | undefined;
  onClose: () => void;
  onDone: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [rejectionReason, setRejectionReason] = useState("");
  const [editingQuality, setEditingQuality] = useState(false);
  const [qualityEdit, setQualityEdit] = useState({
    conforming_cartons: "",
    non_conforming_cartons: "",
    humidity_percentage: "",
    defect_details: "",
  });
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

  const canRaiseNc = Number(qualityDetail?.detail?.non_conforming_cartons ?? 0) > 0;

  // Initialize NC fields when rejecting a quality report with non-conforming cartons
  useEffect(() => {
    if (canRaiseNc && !ncDefectType) {
      setNcDefectType(qualityDetail?.detail?.defect_details || "");
    }
  }, [canRaiseNc, qualityDetail?.detail?.defect_details, ncDefectType]);

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

      // If this is a QC report with non-conforming cartons and user wants to raise NC
      if (canRaiseNc && raiseNc && ncSourceLocationId && ncQuarantineLocationId) {
        try {
          await raiseNonConformity(token, {
            of_id: item.ofId,
            product_id: ofProductId!,
            quantity: ncQuantity,
            source_location_id: ncSourceLocationId,
            quarantine_location_id: ncQuarantineLocationId,
            defect_type: ncDefectType || "Non-conformity detected",
            severity: "minor",
            quality_report_id: item.id,
            description: qualityDetail?.detail?.defect_details || undefined,
            correlation_id: crypto.randomUUID(),
          });
        } catch (ncError) {
          // Rejection succeeded, but NC creation failed — show warning but still finish
          const errorMessage = ncError instanceof ApiError ? ncError.message : String(ncError);
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
    const detail = qualityDetail?.detail;
    setQualityEdit({
      conforming_cartons: String(detail?.conforming_cartons ?? 0),
      non_conforming_cartons: String(detail?.non_conforming_cartons ?? 0),
      humidity_percentage: detail?.humidity_percentage != null ? String(detail.humidity_percentage) : "",
      defect_details: detail?.defect_details ?? "",
    });
    setQualityEditReason("");
    setEditingQuality(true);
  }

  const updateQualityMutation = useMutation({
    // Sent as a full detail object, not just the edited fields: the admin
    // endpoint replaces the whole record, so the indices this dialog doesn't
    // show (pre-dryer, cooling, PF, sumo...) must ride along unchanged.
    mutationFn: () =>
      adminUpdateQualityReport(token, item.id, {
        detail: {
          ...(qualityDetail?.detail ?? ({} as QualityReportDetail)),
          conforming_cartons: Number(qualityEdit.conforming_cartons) || 0,
          non_conforming_cartons: Number(qualityEdit.non_conforming_cartons) || 0,
          humidity_percentage: qualityEdit.humidity_percentage === "" ? null : Number(qualityEdit.humidity_percentage),
          defect_details: qualityEdit.defect_details || null,
        },
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

  // Needed to raise an NC: resolving the product's packets_per_carton converts
  // the rapport's carton count into the piece count the product is actually
  // stocked and moved in.
  const { data: products = [] } = useQuery({
    queryKey: ["core", "products"],
    queryFn: () => listProducts(token),
  });
  const { data: uoms = [] } = useQuery({
    queryKey: ["core", "uoms"],
    queryFn: () => listUoms(token),
  });

  const ncProduct = products.find((p) => p.id === ofProductId);
  const ncPacketsPerCarton = ncProduct?.packets_per_carton && ncProduct.packets_per_carton > 0 ? ncProduct.packets_per_carton : null;
  const ncCartonCount = Number(qualityDetail?.detail?.non_conforming_cartons ?? 0);
  const ncQuantity = ncPacketsPerCarton ? ncCartonCount * ncPacketsPerCarton : ncCartonCount;
  const ncProductUnit = productUnit(ofProductId, products, uoms);

  const figures = qualityFigures(qualityDetail?.detail, !ncPacketsPerCarton);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {reference} · {t("production.validation.source.quality")}
          </DialogTitle>
          <DialogDescription>
            {item.reportDate}
            {item.shift ? ` · ${item.shift}` : ""}
            {item.team ? ` · ${item.team}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border border-border">
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("production.validation.figures")}
              </p>
              {!editingQuality && (
                <Button size="sm" variant="ghost" onClick={openQualityEdit} disabled={!qualityDetail}>
                  <Pencil className="h-3.5 w-3.5" />
                  {t("common.edit")}
                </Button>
              )}
            </div>
            {editingQuality ? (
              <div className="space-y-3 px-4 py-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="q_edit_conforming">
                      {t(ncPacketsPerCarton ? "qc.quality.field.conforming" : "qc.quality.field.conformingSacs")} (
                      {t(ncPacketsPerCarton ? "qc.quality.unit.cartons" : "qc.quality.unit.sacs")})
                    </Label>
                    <Input
                      id="q_edit_conforming"
                      type="number"
                      step="1"
                      value={qualityEdit.conforming_cartons}
                      onChange={(e) => setQualityEdit((s) => ({ ...s, conforming_cartons: e.target.value }))}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="q_edit_non_conforming">
                      {t(ncPacketsPerCarton ? "qc.quality.field.nonConforming" : "qc.quality.field.nonConformingSacs")} (
                      {t(ncPacketsPerCarton ? "qc.quality.unit.cartons" : "qc.quality.unit.sacs")})
                    </Label>
                    <Input
                      id="q_edit_non_conforming"
                      type="number"
                      step="1"
                      value={qualityEdit.non_conforming_cartons}
                      onChange={(e) => setQualityEdit((s) => ({ ...s, non_conforming_cartons: e.target.value }))}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="q_edit_humidity">{t("qc.quality.field.humidity")}</Label>
                    <Input
                      id="q_edit_humidity"
                      type="number"
                      step="any"
                      value={qualityEdit.humidity_percentage}
                      onChange={(e) => setQualityEdit((s) => ({ ...s, humidity_percentage: e.target.value }))}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="q_edit_defects">{t("qc.quality.field.defectDetails")}</Label>
                    <Input
                      id="q_edit_defects"
                      value={qualityEdit.defect_details}
                      onChange={(e) => setQualityEdit((s) => ({ ...s, defect_details: e.target.value }))}
                    />
                  </div>
                </div>
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
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <p className="text-xs text-muted-foreground">{t("production.validation.nc.field.product")}</p>
                      <p className="font-medium">{ncProduct?.name ?? "—"}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{t("production.validation.nc.field.quantity")}</p>
                      <p className="font-medium">{formatQuantity(ncQuantity, ncProductUnit)}</p>
                      {ncPacketsPerCarton && (
                        <p className="text-xs text-muted-foreground">
                          {t("production.validation.nc.field.cartonBreakdown")
                            .replace("{cartons}", String(ncCartonCount))
                            .replace("{perCarton}", String(ncPacketsPerCarton))}
                        </p>
                      )}
                    </div>
                  </div>

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

interface ReviewFigure {
  /** A translation key; `suffix` carries anything that is not translatable. */
  label: string;
  /** An already-readable name shown instead of translating `label`, for a name that has no key. */
  labelText?: string;
  /** Appended after the translated label, e.g. the name of the item lost. */
  suffix?: string;
  value: number | string | null;
  unit?: string | null;
}

function qualityFigures(
  detail: { conforming_cartons: number; non_conforming_cartons: number; humidity_percentage: number | null; defect_details: string | null } | null | undefined,
  isSac: boolean,
): ReviewFigure[] {
  if (!detail) return [];
  const unit = isSac ? "sacs" : "cartons";
  return [
    { label: isSac ? "qc.quality.field.conformingSacs" : "qc.quality.field.conforming", value: detail.conforming_cartons, unit },
    { label: isSac ? "qc.quality.field.nonConformingSacs" : "qc.quality.field.nonConforming", value: detail.non_conforming_cartons, unit },
    { label: "qc.quality.field.humidity", value: detail.humidity_percentage ?? "—", unit: "%" },
    { label: "qc.quality.field.defectDetails", value: detail.defect_details ?? "—" },
  ];
}
