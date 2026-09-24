import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { ArrowDown, ArrowUp, CalendarClock, OctagonPause, PackageCheck, Plus, Recycle, RotateCcw, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { EmptyState } from "../../components/patterns/EmptyState";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import {
  REPORT_OPTIONS_QUERY_KEY,
  createReportOption,
  deleteReportOption,
  listReportOptions,
  updateReportOption,
  type ReportOption,
  type ReportOptionKind,
} from "../../lib/reportOptions";
import { listPackagingTolerances, listProducts, listRegrindDefaults, setPackagingTolerance, setRegrindDefault } from "./api";
import { listFollowUpPolicies, setFollowUpPolicy } from "../qc/api";
import { DOWNTIME_OPTION_KIND } from "./downtimeOptions";
import { DashboardSettingsCard } from "./DashboardSettingsCard";
import { WasteTypesCard } from "./WasteTypesCard";
import { AppLoader } from "../../components/patterns/AppLoader";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const REGRIND_DEFAULTS_QUERY_KEY = ["production", "regrind-defaults"] as const;
const FOLLOW_UP_POLICIES_QUERY_KEY = ["qc", "follow-up-policies"] as const;
const PACKAGING_TOLERANCES_QUERY_KEY = ["production", "packaging-tolerances"] as const;

/**
 * Everything about production that used to be set with SQL.
 *
 * Three settings reached this screen for the same reason: each one silently
 * decides how a report behaves, and none of them had anywhere to be changed. A
 * daily report with rebroyat cannot validate without a regrind default, a
 * validated quality report opens a window whose length nobody could see, and the
 * shift a report is filed under was free text.
 */
export function ProductionSettingsTab() {
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <OptionListCard kind="shift" title={t("production.settings.shifts.title")} description={t("production.settings.shifts.description")} />
        <OptionListCard kind="team" title={t("production.settings.teams.title")} description={t("production.settings.teams.description")} />
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <RegrindDefaultsCard />
        <FollowUpPolicyCard />
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <PackagingToleranceCard />
        <WasteTypesCard />
      </div>
      {/*
        The arrêt vocabulary. The built-in values ship with the app; these lists
        are the plant's own additions, offered beside them on every arrêt line.
      */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {(["type", "classification", "motif"] as const).map((field) => (
          <OptionListCard
            key={field}
            kind={DOWNTIME_OPTION_KIND[field]}
            icon={OctagonPause}
            title={t(`production.settings.downtime.${field}.title` as TranslationKey)}
            description={t("production.settings.downtime.description")}
            placeholder={t(`production.settings.downtime.${field}.placeholder` as TranslationKey)}
            emptyDescription={t("production.settings.downtime.empty")}
          />
        ))}
      </div>
      <DashboardSettingsCard />
    </div>
  );
}

/** One editable list — the shifts, or the teams. */
function OptionListCard({
  kind,
  title,
  description,
  icon: Icon = Users,
  placeholder,
  emptyDescription,
}: {
  kind: ReportOptionKind;
  title: string;
  description: string;
  icon?: LucideIcon;
  placeholder?: string;
  /** For lists that start non-empty in effect, where "leave it blank" would be wrong. */
  emptyDescription?: string;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [newLabel, setNewLabel] = useState("");

  // Retired names are shown here even though the report forms no longer offer
  // them: this is where someone comes to understand why an old report says
  // "Nuit" when the list does not.
  const { data: options = [], isLoading } = useQuery({
    queryKey: [...REPORT_OPTIONS_QUERY_KEY, "all"],
    queryFn: () => listReportOptions(token, true),
  });
  const mine = options
    .filter((option) => option.kind === kind)
    .sort((a, b) => a.sort_order - b.sort_order || a.label.localeCompare(b.label));

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: REPORT_OPTIONS_QUERY_KEY });
  }

  function onError(error: unknown) {
    toast.error(t("production.settings.saveError"), {
      description: error instanceof ApiError ? error.message : undefined,
    });
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createReportOption(token, {
        kind,
        label: newLabel,
        // New entries go to the end; the arrows are how they are ordered.
        sort_order: mine.length === 0 ? 1 : Math.max(...mine.map((o) => o.sort_order)) + 1,
      }),
    onSuccess: () => {
      invalidate();
      setNewLabel("");
      toast.success(t("production.settings.saved"));
    },
    onError,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...input }: { id: string; label?: string; sort_order?: number; is_active?: boolean }) =>
      updateReportOption(token, id, input),
    onSuccess: () => {
      invalidate();
      toast.success(t("production.settings.saved"));
    },
    onError,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteReportOption(token, id),
    onSuccess: (result) => {
      invalidate();
      // Retiring and deleting are different outcomes and the user needs to know
      // which one happened — a retired name is still on every old report.
      toast.success(
        result.outcome === "retired"
          ? t("production.settings.options.retired")
          : t("production.settings.options.deleted"),
      );
    },
    onError,
  });

  /** Swap sort_order with the neighbour, which is what "move up" means here. */
  function move(option: ReportOption, direction: -1 | 1) {
    const index = mine.findIndex((o) => o.id === option.id);
    const neighbour = mine[index + direction];
    if (!neighbour) return;
    updateMutation.mutate({ id: option.id, sort_order: neighbour.sort_order });
    updateMutation.mutate({ id: neighbour.id, sort_order: option.sort_order });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <Icon className="h-4 w-4" />
          {title}
        </CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : mine.length === 0 ? (
          <EmptyState
            icon={<Icon className="h-5 w-5" />}
            title={t("production.settings.options.empty.title")}
            description={emptyDescription ?? t("production.settings.options.empty.description")}
          />
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            <AnimatePresence initial={false}>
              {mine.map((option, index) => (
                <motion.li
                  key={option.id}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center gap-2 p-2"
                >
                  <div className="flex flex-col">
                    <button
                      type="button"
                      aria-label={t("production.settings.options.moveUp")}
                      className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
                      disabled={index === 0}
                      onClick={() => move(option, -1)}
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={t("production.settings.options.moveDown")}
                      className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
                      disabled={index === mine.length - 1}
                      onClick={() => move(option, 1)}
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <Input
                    defaultValue={option.label}
                    className={option.is_active ? undefined : "text-muted-foreground line-through"}
                    onBlur={(event) => {
                      const label = event.target.value.trim();
                      if (label && label !== option.label) updateMutation.mutate({ id: option.id, label });
                    }}
                  />
                  {!option.is_active && <Badge variant="outline">{t("production.settings.options.retiredBadge")}</Badge>}
                  {option.is_active ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("common.delete")}
                      onClick={() => deleteMutation.mutate(option.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("production.settings.options.restore")}
                      onClick={() => updateMutation.mutate({ id: option.id, is_active: true })}
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}

        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (newLabel.trim()) createMutation.mutate();
          }}
        >
          <Input
            value={newLabel}
            onChange={(event) => setNewLabel(event.target.value)}
            placeholder={placeholder ?? t("production.settings.options.newPlaceholder")}
          />
          <Button type="submit" size="sm" disabled={!newLabel.trim() || createMutation.isPending}>
            <Plus className="h-3.5 w-3.5" />
            {t("common.add")}
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">{t("production.settings.options.help")}</p>
      </CardContent>
    </Card>
  );
}

/** Which product a regrind yields, tenant-wide and per input. */
/**
 * One product, tenant-wide — every regrind batch becomes stock of this and
 * nothing else. There used to be a per-input override here; it's gone because
 * `create_regrind_batch` never reads it any more, and a setting that silently
 * does nothing is worse than no setting at all. See the backend comment on
 * that method for why: two operators regrinding the same kind of scrap used
 * to be able to land on two different products, fragmenting the stock that
 * should have been one line.
 */
function RegrindDefaultsCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [outputProduct, setOutputProduct] = useState("");

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: defaults = [], isLoading } = useQuery({
    queryKey: REGRIND_DEFAULTS_QUERY_KEY,
    queryFn: () => listRegrindDefaults(token),
  });
  const current = defaults.find((row) => row.input_product_id === null) ?? null;

  const nameOf = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;

  const mutation = useMutation({
    mutationFn: () => setRegrindDefault(token, outputProduct),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REGRIND_DEFAULTS_QUERY_KEY });
      setOutputProduct("");
      toast.success(t("production.settings.saved"));
    },
    onError: (error) => {
      toast.error(t("production.settings.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <Recycle className="h-4 w-4" />
          {t("production.settings.regrind.title")}
          <HelpTooltip text={t("production.settings.regrind.help")} />
        </CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("production.settings.regrind.description")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : current === null ? (
          <EmptyState
            icon={<Recycle className="h-5 w-5" />}
            title={t("production.settings.regrind.empty.title")}
            description={t("production.settings.regrind.empty.description")}
          />
        ) : (
          <div className="rounded-lg border border-border p-2.5 text-sm">
            <span className="text-muted-foreground">{t("production.settings.regrind.current")} </span>
            <span className="font-medium">{nameOf(current.output_product_id)}</span>
          </div>
        )}

        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (outputProduct) mutation.mutate();
          }}
        >
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="regrind_output">{t("production.settings.regrind.output")}</Label>
            <Select id="regrind_output" value={outputProduct} onChange={(event) => setOutputProduct(event.target.value)}>
              <option value="">—</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" size="sm" disabled={!outputProduct || mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

/** How long quality keeps watching a validated report. */
function FollowUpPolicyCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [product, setProduct] = useState("");
  const [windowDays, setWindowDays] = useState("40");

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: policies = [], isLoading } = useQuery({
    queryKey: FOLLOW_UP_POLICIES_QUERY_KEY,
    queryFn: () => listFollowUpPolicies(token),
  });

  const nameOf = (productId: string | null) =>
    productId === null
      ? t("production.settings.followUp.allProducts")
      : products.find((p) => p.id === productId)?.name ?? productId;

  const mutation = useMutation({
    mutationFn: () => setFollowUpPolicy(token, Number(windowDays), product || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: FOLLOW_UP_POLICIES_QUERY_KEY });
      setProduct("");
      toast.success(t("production.settings.saved"));
    },
    onError: (error) => {
      toast.error(t("production.settings.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <CalendarClock className="h-4 w-4" />
          {t("production.settings.followUp.title")}
          <HelpTooltip text={t("production.settings.followUp.help")} />
        </CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("production.settings.followUp.description")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : policies.length === 0 ? (
          <EmptyState
            icon={<CalendarClock className="h-5 w-5" />}
            title={t("production.settings.followUp.empty.title")}
            description={t("production.settings.followUp.empty.description")}
          />
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {policies.map((policy) => (
              <li key={policy.product_id ?? "default"} className="flex items-center justify-between gap-3 p-2.5 text-sm">
                <span className={policy.product_id === null ? "font-medium" : undefined}>
                  {nameOf(policy.product_id)}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {policy.window_days} {t("production.settings.followUp.days")}
                </span>
              </li>
            ))}
          </ul>
        )}

        <form
          className="grid grid-cols-1 gap-2 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (Number(windowDays) > 0) mutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="policy_product">{t("production.settings.followUp.product")}</Label>
            <Select id="policy_product" value={product} onChange={(event) => setProduct(event.target.value)}>
              <option value="">{t("production.settings.followUp.allProducts")}</option>
              {products.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="policy_window">{t("production.settings.followUp.window")}</Label>
            <Input
              id="policy_window"
              type="number"
              min={1}
              value={windowDays}
              onChange={(event) => setWindowDays(event.target.value)}
            />
          </div>
          <Button
            type="submit"
            size="sm"
            className="sm:col-span-2"
            disabled={Number(windowDays) <= 0 || mutation.isPending}
          >
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

/** The percentage at which a packaging ecart stops looking like rounding. */
function PackagingToleranceCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [product, setProduct] = useState("");
  // Deliberately empty: a tolerance is the plant's decision, not something to suggest.
  const [tolerance, setTolerance] = useState("");

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: tolerances = [], isLoading } = useQuery({
    queryKey: PACKAGING_TOLERANCES_QUERY_KEY,
    queryFn: () => listPackagingTolerances(token),
  });

  const nameOf = (productId: string | null) =>
    productId === null
      ? t("production.settings.followUp.allProducts")
      : products.find((p) => p.id === productId)?.name ?? productId;

  const valid = tolerance.trim() !== "" && Number(tolerance) >= 0;
  const mutation = useMutation({
    mutationFn: () =>
      setPackagingTolerance(token, { product_id: product || null, tolerance_percent: Number(tolerance) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PACKAGING_TOLERANCES_QUERY_KEY });
      // Every screen that judges an ecart reads this tolerance, so refetch them all.
      queryClient.invalidateQueries({ queryKey: ["production", "packaging-variance"] });
      setProduct("");
      setTolerance("");
      toast.success(t("production.settings.saved"));
    },
    onError: (error) => {
      toast.error(t("production.settings.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <PackageCheck className="h-4 w-4" />
          {t("production.settings.tolerance.title")}
          <HelpTooltip text={t("production.settings.tolerance.help")} />
        </CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("production.settings.tolerance.description")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : tolerances.length === 0 ? (
          <EmptyState
            icon={<PackageCheck className="h-5 w-5" />}
            title={t("production.settings.tolerance.empty.title")}
            description={t("production.settings.tolerance.empty.description")}
          />
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {tolerances.map((entry) => (
              <li key={entry.product_id ?? "default"} className="flex items-center justify-between gap-3 p-2.5 text-sm">
                <span className={entry.product_id === null ? "font-medium" : undefined}>{nameOf(entry.product_id)}</span>
                <span className="tabular-nums text-muted-foreground">{entry.tolerance_percent} %</span>
              </li>
            ))}
          </ul>
        )}

        <form
          className="grid grid-cols-1 gap-2 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) mutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="tolerance_product">{t("production.settings.followUp.product")}</Label>
            <Select id="tolerance_product" value={product} onChange={(event) => setProduct(event.target.value)}>
              <option value="">{t("production.settings.followUp.allProducts")}</option>
              {products.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tolerance_percent">{t("production.settings.tolerance.field")}</Label>
            <Input
              id="tolerance_percent"
              type="number"
              min={0}
              step="any"
              value={tolerance}
              onChange={(event) => setTolerance(event.target.value)}
            />
          </div>
          <Button type="submit" size="sm" className="sm:col-span-2" disabled={!valid || mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
