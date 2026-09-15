import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ClipboardCheck, Inbox, Pencil, XCircle } from "lucide-react";
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
import { Skeleton } from "../../components/ui/skeleton";
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
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { BulkActionBar } from "../../components/patterns/BulkActionBar";
import { useSelection } from "../../lib/useSelection";
import { cn } from "../../lib/utils";
import { RecipeCheckPanel } from "./RecipeCheckPanel";
import { PackagingVariancePanel } from "./PackagingVariancePanel";
import {
  type ConditionnementReportDetail,
  type DailyReportDetail,
  getReport,
  getReportPackagingVariance,
  listProducts,
  listReports,
  listWorkCenters,
  listWorkOrders,
  type ProductionReport,
  rejectReport,
  validateReport,
  type WasteLine,
} from "./api";
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

import { UTILITY_UNITS, formatDuration, formatQuantity, productUnit } from "../../lib/units";
import { listLocations, listUoms } from "../warehouse/api";
const PRODUCTION_QUERY_KEY = ["production", "reports", "pending"] as const;
const QUALITY_QUERY_KEY = ["qc", "quality-reports", "pending"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

type Source = "daily" | "conditionnement" | "quality";
type SourceFilter = "all" | Source;

/**
 * One queue, two services. Production owns the daily and conditionnement reports
 * and qc owns the quality report — the Validation Center calls both rather than
 * either module reaching into the other's tables.
 */
interface PendingItem {
  id: string;
  source: Source;
  ofId: string;
  reportDate: string;
  team: string | null;
  shift: string | null;
  submittedAt: string | null;
}

// id alone can collide across the two services this queue merges (a daily
// report and a quality report minted from the same OF/date can share an id),
// so selection is keyed on source+id rather than id alone.
function itemKey(item: PendingItem): string {
  return `${item.source}:${item.id}`;
}

export function ValidationCenterTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [reviewing, setReviewing] = useState<PendingItem | null>(null);

  const { data: productionReports = [], isLoading: loadingProduction } = useQuery({
    queryKey: PRODUCTION_QUERY_KEY,
    queryFn: () => listReports(token, { status: "submitted" }),
  });
  const { data: qualityReports = [], isLoading: loadingQuality } = useQuery({
    queryKey: QUALITY_QUERY_KEY,
    queryFn: () => listQualityReports(token, { status: "submitted" }),
  });
  const { data: workOrders = [] } = useQuery({
    queryKey: WORK_ORDERS_QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });

  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;

  const items: PendingItem[] = [
    ...productionReports.map((r: ProductionReport) => ({
      id: r.id,
      source: r.report_type as Source,
      ofId: r.of_id,
      reportDate: r.report_date,
      team: r.team,
      shift: r.shift,
      submittedAt: r.submitted_at,
    })),
    ...qualityReports.map((r: QualityReport) => ({
      id: r.id,
      source: "quality" as const,
      ofId: r.of_id,
      reportDate: r.report_date,
      team: r.team,
      shift: r.shift,
      submittedAt: r.submitted_at,
    })),
  ].sort((a, b) => (a.submittedAt ?? "").localeCompare(b.submittedAt ?? ""));

  const visible = sourceFilter === "all" ? items : items.filter((i) => i.source === sourceFilter);

  // One card per work order, its pending reports nested underneath — a validator
  // reviews an order's shift, not a flat list of unrelated rows.
  const grouped = Array.from(
    visible.reduce((map, item) => {
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
      dateRange: first === last ? first : `${first} \u2192 ${last}`,
    };
  });

  function invalidateEverything() {
    // Validation posts stock, so it reaches well past this queue.
    for (const key of [
      PRODUCTION_QUERY_KEY,
      QUALITY_QUERY_KEY,
      ["production", "reports", "daily"],
      ["production", "reports", "conditionnement"],
      ["production", "work-order-yields"],
      ["production", "regrind-batches"],
      ["production", "scrap-records"],
      ["qc", "quality-reports"],
      ["qc", "follow-ups"],
      ["warehouse", "stock"],
      ["warehouse", "stock", "moves"],
    ]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  }

  const selection = useSelection(visible.map(itemKey));
  const [bulkValidateOpen, setBulkValidateOpen] = useState(false);
  const [bulkRejectOpen, setBulkRejectOpen] = useState(false);
  const [bulkRejectReason, setBulkRejectReason] = useState("");
  const selectedItems = visible.filter((item) => selection.isSelected(itemKey(item)));

  // Straight validate/reject only -- no shortfall comment, no regrind work
  // center override, no quality corrections. An item that needs any of that
  // simply fails here and stays pending, to be handled in the individual
  // review dialog above.
  const bulkValidateMutation = useMutation({
    mutationFn: async () => {
      const settled = await Promise.allSettled(
        selectedItems.map((item) =>
          item.source === "quality"
            ? validateQualityReport(token, item.id, crypto.randomUUID())
            : validateReport(token, item.id, { correlationId: crypto.randomUUID() }),
        ),
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
        selectedItems.map((item) =>
          item.source === "quality" ? rejectQualityReport(token, item.id, reason) : rejectReport(token, item.id, reason),
        ),
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

  const isLoading = loadingProduction || loadingQuality;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          label={t("production.validation.stat.daily")}
          value={items.filter((i) => i.source === "daily").length}
          icon={<ClipboardCheck className="h-5 w-5" />}
          accent="warning"
        />
        <StatCard
          label={t("production.validation.stat.conditionnement")}
          value={items.filter((i) => i.source === "conditionnement").length}
          icon={<ClipboardCheck className="h-5 w-5" />}
          accent="primary"
        />
        <StatCard
          label={t("production.validation.stat.quality")}
          value={items.filter((i) => i.source === "quality").length}
          icon={<ClipboardCheck className="h-5 w-5" />}
          accent="accent"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.validation.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.validation.subtitle")}</p>
            </div>
            <FilterTabs
              options={[
                { value: "all", label: t("common.all") },
                { value: "daily", label: t("production.validation.source.daily") },
                { value: "conditionnement", label: t("production.validation.source.conditionnement") },
                { value: "quality", label: t("production.validation.source.quality") },
              ]}
              value={sourceFilter}
              onChange={setSourceFilter}
            />
          </div>
        </CardHeader>
        <CardContent className={grouped.length === 0 ? "p-0" : "space-y-3"}>
          {!isLoading && visible.length > 0 && (
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
                      <div key={itemKey(item)} className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium">{referenceOf(item.ofId)}</span>
                        <span className="text-muted-foreground">
                          {t(sourceLabelKey(item.source))} · {item.reportDate}
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
                      <div key={itemKey(item)} className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium">{referenceOf(item.ofId)}</span>
                        <span className="text-muted-foreground">
                          {t(sourceLabelKey(item.source))} · {item.reportDate}
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
            <div className="space-y-2 p-6">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : grouped.length === 0 ? (
            <EmptyState
              icon={<Inbox className="h-5 w-5" />}
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
                  {/* The order is the unit of work a validator thinks in: they
                      approve a shift's output, not three unrelated rows. */}
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
                        key={itemKey(item)}
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
                        {/* Stops the row's own onClick -- picking a report for
                            bulk action must not also open its review dialog. */}
                        <div onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={selection.isSelected(itemKey(item))}
                            onCheckedChange={() => selection.toggle(itemKey(item))}
                            aria-label={t("production.validation.review")}
                          />
                        </div>
                        <div
                          className={cn(
                            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                            item.source === "daily" && "bg-warning-soft text-warning",
                            item.source === "conditionnement" && "bg-primary/10 text-primary",
                            item.source === "quality" && "bg-accent/10 text-accent",
                          )}
                        >
                          <ClipboardCheck className="h-4 w-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline">{t(sourceLabelKey(item.source))}</Badge>
                            <span className="text-sm text-muted-foreground">
                              {item.reportDate}
                              {item.shift ? ` \u00b7 ${item.shift}` : ""}
                              {item.team ? ` \u00b7 ${item.team}` : ""}
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

function sourceLabelKey(source: Source) {
  if (source === "daily") return "production.validation.source.daily" as const;
  if (source === "conditionnement") return "production.validation.source.conditionnement" as const;
  return "production.validation.source.quality" as const;
}

/**
 * The review panel. Loads the report's figures on demand so a validator sees what
 * they are approving, then validates or rejects it.
 *
 * The shortfall field is the interesting one: a report that consumes more than
 * the stock figure holds still posts — the report records what physically
 * happened — but the backend refuses it with SHORTFALL_COMMENT_REQUIRED until the
 * validator explains it, and this is where that explanation is typed.
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
  const [shortfallComment, setShortfallComment] = useState("");
  const [shortfallRequired, setShortfallRequired] = useState(false);
  const [regrindWorkCenterId, setRegrindWorkCenterId] = useState("");
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

  const isQuality = item.source === "quality";

  const { data: productionDetail } = useQuery({
    queryKey: ["production", "reports", item.id],
    queryFn: () => getReport(token, item.id),
    enabled: !isQuality,
  });
  const { data: qualityDetail } = useQuery({
    queryKey: ["qc", "quality-reports", item.id],
    queryFn: () => getQualityReport(token, item.id),
    enabled: isQuality,
  });
  const { data: workCenters = [] } = useQuery({
    queryKey: WORK_CENTERS_QUERY_KEY,
    queryFn: () => listWorkCenters(token),
    enabled: !isQuality,
  });
  const { data: locations = [] } = useQuery({
    queryKey: LOCATIONS_QUERY_KEY,
    queryFn: () => listLocations(token),
    enabled: isQuality,
  });

  // Only a daily report carrying rebroyat opens a regrind OF (decision 11), and
  // that OF runs on its own line — not necessarily the one that filed the
  // report — so the validator picks it here, at the moment it opens. Left
  // untouched, it falls back to the report's own work center (decision 15).
  const hasRebroyat =
    !isQuality && item.source === "daily" && Number((productionDetail?.detail as DailyReportDetail | undefined)?.regrind_quantity ?? 0) > 0;
  const effectiveRegrindWorkCenterId = regrindWorkCenterId || productionDetail?.work_center_id || "";

  const canRaiseNc = isQuality && Number(qualityDetail?.detail?.non_conforming_cartons ?? 0) > 0;

  // Initialize NC fields when rejecting a quality report with non-conforming cartons
  useEffect(() => {
    if (canRaiseNc && !ncDefectType) {
      setNcDefectType(qualityDetail?.detail?.defect_details || "");
    }
  }, [canRaiseNc, qualityDetail?.detail?.defect_details, ncDefectType]);

  const validateMutation = useMutation({
    // The two services return different shapes; the queue only cares that it
    // succeeded, so the result is deliberately discarded.
    mutationFn: async (): Promise<void> => {
      if (isQuality) {
        await validateQualityReport(token, item.id, crypto.randomUUID());
        return;
      }
      await validateReport(token, item.id, {
        correlationId: crypto.randomUUID(),
        shortfallComment: shortfallComment || undefined,
        regrindWorkCenterId: hasRebroyat ? effectiveRegrindWorkCenterId || undefined : undefined,
      });
    },
    onSuccess: () => {
      toast.success(t("production.validation.validated"));
      onDone();
    },
    onError: (error) => {
      // The one refusal that is a prompt rather than a failure: the movement is
      // allowed, it just needs an explanation first.
      if (error instanceof ApiError && error.message.includes("comment")) {
        setShortfallRequired(true);
        toast.warning(t("production.validation.shortfallPrompt"));
        return;
      }
      toast.error(t("production.validation.validateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (isQuality) {
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
        return;
      }
      await rejectReport(token, item.id, rejectionReason);
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

  // Needed on the quality path too: raising an NC has to resolve the product's
  // packets_per_carton to convert the rapport's carton count into the piece
  // count the product is actually stocked and moved in.
  const { data: products = [] } = useQuery({
    queryKey: ["core", "products"],
    queryFn: () => listProducts(token),
  });
  const { data: uoms = [] } = useQuery({
    queryKey: ["core", "uoms"],
    queryFn: () => listUoms(token),
  });

  // The quality rapport declares non-conforming stock in cartons, but an NC's
  // `quantity` (and the stock transfer it drives) is in the product's own unit
  // -- pieces for anything with a carton tier. Without this conversion, "1
  // carton" of a 20-per-carton product was raised and quarantined as 1 piece.
  const ncProduct = products.find((p) => p.id === ofProductId);
  const ncPacketsPerCarton = ncProduct?.packets_per_carton && ncProduct.packets_per_carton > 0 ? ncProduct.packets_per_carton : null;
  const ncCartonCount = Number(qualityDetail?.detail?.non_conforming_cartons ?? 0);
  const ncQuantity = ncPacketsPerCarton ? ncCartonCount * ncPacketsPerCarton : ncCartonCount;
  const ncProductUnit = productUnit(ofProductId, products, uoms);

  // Each figure is shown in the unit the warehouse will actually move it in.
  const daily = productionDetail?.detail as DailyReportDetail | undefined;
  const packing = productionDetail?.detail as ConditionnementReportDetail | undefined;
  const units = {
    of: productUnit(ofProductId, products, uoms),
    semolina: productUnit(daily?.semolina_lines?.[0]?.product_id, products, uoms),
    regrind: productUnit(daily?.regrind_input_product_id, products, uoms),
    regrindOutput: productUnit(daily?.regrind_product_id, products, uoms),
    film: productUnit(packing?.film_product_id, products, uoms),
    carton: productUnit(packing?.carton_product_id, products, uoms),
    scotch: productUnit(packing?.scotch_product_id, products, uoms),
    ruban: productUnit(packing?.ruban_product_id, products, uoms),
  };

  const { data: packingVariance } = useQuery({
    queryKey: ["production", "packaging-variance", "report", item.id],
    queryFn: () => getReportPackagingVariance(session!.token, item.id),
    enabled: item.source === "conditionnement",
  });

  // A validator judging a déchet needs to know what three of. Resolving the item
  // here rather than in the figure builder keeps that function free of queries.
  const wasteFigures: ReviewFigure[] = (
    (productionDetail?.detail as { waste_lines?: WasteLine[] } | undefined)?.waste_lines ?? []
  ).map((line) => ({
    label: `production.waste.category.${line.category}`,
    suffix:
      (line.product_id && products.find((p) => p.id === line.product_id)?.name) ||
      t("production.waste.unknownItem"),
    value: line.quantity,
    // The daily report's déchets are always weighed in kg -- see
    // WasteLinesField's fixedUnit. Conditionnement's stay per-product.
    unit: item.source === "daily" ? "kg" : productUnit(line.product_id, products, uoms),
  }));

  const figures = isQuality
    ? qualityFigures(qualityDetail?.detail, !ncPacketsPerCarton)
    : [...productionFigures(item.source, productionDetail?.detail, units, products, uoms), ...wasteFigures];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {reference} · {t(sourceLabelKey(item.source))}
          </DialogTitle>
          <DialogDescription>
            {item.reportDate}
            {item.shift ? ` · ${item.shift}` : ""}
            {item.team ? ` · ${item.team}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* The écart de conditionnement, above the figures it reads. Gross, and
              never a gate (decision 22): it is here so a mis-weigh or a miscount
              is caught while the shift is still fresh in someone's memory. */}
          {item.source === "conditionnement" && packingVariance && (
            <PackagingVariancePanel variance={packingVariance} />
          )}

          <div className="rounded-lg border border-border">
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("production.validation.figures")}
              </p>
              {isQuality && !editingQuality && (
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
                  // Keyed by position: two déchets of the same stage are two rows.
                  <div key={`${f.label}:${index}`} className="flex items-baseline justify-between gap-3">
                    <dt className="text-sm text-muted-foreground">
                      {t(f.label as Parameters<typeof t>[0])}
                      {f.suffix ? ` — ${f.suffix}` : ""}
                    </dt>
                    <dd className="text-sm font-medium tabular-nums">
                      {typeof f.value === "string"
                        ? f.value
                        : f.duration
                          ? formatDuration(f.value)
                          : formatQuantity(f.value, f.unit)}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>

          {hasRebroyat && (
            <div className="space-y-1.5">
              <Label htmlFor="regrind_work_center">{t("production.validation.field.regrindWorkCenter")}</Label>
              <Select
                id="regrind_work_center"
                value={effectiveRegrindWorkCenterId}
                onChange={(e) => setRegrindWorkCenterId(e.target.value)}
              >
                <option value="">—</option>
                {workCenters.map((wc) => (
                  <option key={wc.id} value={wc.id}>
                    {wc.code} — {wc.name}
                  </option>
                ))}
              </Select>
            </div>
          )}

          {!isQuality && (
            <div className="space-y-1.5">
              <Label htmlFor="shortfall">{t("production.validation.field.shortfallComment")}</Label>
              <Input
                id="shortfall"
                value={shortfallComment}
                onChange={(e) => setShortfallComment(e.target.value)}
                placeholder={t("production.validation.field.shortfallPlaceholder")}
              />
              {shortfallRequired && (
                <p className="flex items-center gap-1.5 text-sm text-warning">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {t("production.validation.shortfallRequired")}
                </p>
              )}
            </div>
          )}

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
          {/* Validating is what moves the stock, so this is the last moment the
              drift can be noticed before the figures become inventory. */}
          {!isQuality && <RecipeCheckPanel workOrderId={item.ofId} products={products} />}

          <p className="text-xs text-muted-foreground">{t("production.validation.stockNote")}</p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface ReviewFigure {
  /** A translation key; `suffix` carries anything that is not translatable. */
  label: string;
  /** Appended after the translated label, e.g. the name of the item lost. */
  suffix?: string;
  value: number | string | null;
  unit?: string | null;
  duration?: boolean;
}

function productionFigures(
  source: Source,
  detail: DailyReportDetail | ConditionnementReportDetail | null | undefined,
  units: {
    of: string | null;
    semolina: string | null;
    regrind: string | null;
    regrindOutput: string | null;
    film: string | null;
    carton: string | null;
    scotch: string | null;
    ruban: string | null;
  },
  products: { id: string; name: string; uom_id: string }[],
  uoms: { id: string; code: string }[],
): ReviewFigure[] {
  if (!detail) return [];
  if (source === "daily") {
    const d = detail as DailyReportDetail;
    const semolinaLines: ReviewFigure[] = d.semolina_lines.map((line) => ({
      label: "production.dailyReports.field.semolina",
      suffix: (line.product_id && products.find((p) => p.id === line.product_id)?.name) || undefined,
      value: line.quantity,
      unit: productUnit(line.product_id, products, uoms),
    }));
    return [
      ...semolinaLines,
      { label: "production.dailyReports.field.regrindInput", value: d.regrind_input_quantity, unit: units.regrind },
      { label: "production.reports.field.finishedProduct", value: d.finished_product_quantity, unit: units.of },
      // Rebroyat is weighed as its own item, not as semoule: what goes back
      // through the mill is ground pasta, not the flour it was made from.
      { label: "production.dailyReports.field.regrind", value: d.regrind_quantity, unit: units.regrindOutput },
      { label: "production.dailyReports.field.waterPercentage", value: d.water_percentage, unit: "%" },
      { label: "production.dailyReports.field.water", value: d.water_quantity, unit: UTILITY_UNITS.water },
      { label: "production.dailyReports.field.fuel", value: d.fuel_quantity, unit: UTILITY_UNITS.fuel },
      { label: "production.dailyReports.field.gasoil", value: d.gasoil_quantity, unit: UTILITY_UNITS.gasoil },
      { label: "production.dailyReports.field.electricity", value: d.electricity_quantity, unit: UTILITY_UNITS.electricity },
      { label: "production.dailyReports.field.semolinaFlowRate", value: d.semolina_flow_rate, unit: "t/h" },
      { label: "production.reports.field.productionMinutes", value: d.production_minutes, duration: true },
      // One row per arrêt -- a shift may have stopped more than once, for more
      // than one reason, since downtime became a list.
      ...d.downtime_lines.map((line) => ({
        label: "production.reports.field.downtimeMinutes",
        suffix: line.motif ?? undefined,
        value: line.minutes,
        duration: true,
      })),
    ];
  }
  const c = detail as ConditionnementReportDetail;
  return [
    // Decision 24: cartons lead -- for a product with a carton tier, this is
    // what decides the finished-goods quantity, not the machine's tally beside it.
    { label: "production.conditionnement.field.carton", value: c.carton_quantity, unit: units.carton },
    { label: "production.conditionnement.field.wasteCarton", value: c.waste_carton_quantity, unit: units.carton },
    { label: "production.conditionnement.field.packetsCounted", value: c.packets_counted, unit: units.of },
    { label: "production.conditionnement.field.film", value: c.film_quantity, unit: units.film },
    { label: "production.conditionnement.field.scotch", value: c.scotch_quantity, unit: units.scotch },
    { label: "production.conditionnement.field.ruban", value: c.ruban_quantity, unit: units.ruban },
    { label: "production.conditionnement.field.lotNumber", value: c.lot_number ?? "—" },
    { label: "production.conditionnement.field.dlc", value: c.dlc_date ?? "—" },
    { label: "production.reports.field.productionMinutes", value: c.production_minutes, duration: true },
    { label: "production.reports.field.downtimeMinutes", value: c.downtime_minutes, duration: true },
  ];
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
