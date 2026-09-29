import { useState, type ComponentType } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  BadgeCheck,
  Banknote,
  Calculator,
  Info,
  Landmark,
  ListChecks,
  Printer,
  Receipt,
  Undo2,
  UserMinus,
  Wallet,
  X,
} from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useApproveRun, useCalculateRun, useMarkPaid, useRuleSet, useRun } from "../api";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";
import { formatPeriod, formatXof } from "../format";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { PayslipsPanel } from "./run/PayslipsPanel";
import { ReverseDialog } from "./run/ReverseDialog";
import { SettlementsPanel } from "./run/SettlementsPanel";

type Tab = "payslips" | "variance" | "settlements" | "payouts" | "declarations";

interface TabDef {
  value: Tab;
  labelKey: TranslationKey;
  icon: ComponentType<{ className?: string }>;
  permission: string;
}

const TABS: TabDef[] = [
  { value: "payslips", labelKey: "payroll.run.tab.payslips", icon: Receipt, permission: "payroll.view_runs" },
  { value: "variance", labelKey: "payroll.run.tab.variance", icon: ArrowLeftRight, permission: "payroll.view_runs" },
  { value: "settlements", labelKey: "payroll.run.tab.settlements", icon: UserMinus, permission: "payroll.view_runs" },
  { value: "payouts", labelKey: "payroll.run.tab.payouts", icon: Banknote, permission: "payroll.view_runs" },
  { value: "declarations", labelKey: "payroll.run.tab.declarations", icon: Landmark, permission: "payroll.view_declarations" },
];

/** A refused lifecycle action, kept on screen until dismissed or the next action. */
interface Refusal {
  title: string;
  message: string;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: run, isLoading, isError } = useRun(runId);
  const calculate = useCalculateRun();
  const approve = useApproveRun();
  const markPaid = useMarkPaid();
  const [reverseOpen, setReverseOpen] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);

  // A run calculated from a draft rule set names it through rule_set_in_force while that set is still
  // the one in force; otherwise its name is looked up (Rules readers only; others see the id).
  const ownDraftId = run?.rule_set_status === "draft" ? run.rule_set_id : null;
  const lookupId = ownDraftId && run?.rule_set_in_force?.id !== ownDraftId && hasPermission("payroll.view_rules") ? ownDraftId : undefined;
  const { data: ownRuleSet } = useRuleSet(lookupId);

  // The tab lives in the URL so a link can land straight on it.
  const tabs = TABS.filter((entry) => hasPermission(entry.permission));
  const requested = searchParams.get("tab");
  const tab: Tab = tabs.find((entry) => entry.value === requested)?.value ?? "payslips";
  const setTab = (value: Tab) => setSearchParams({ tab: value }, { replace: true });

  if (isLoading) return <AppLoader label={t("payroll.common.loading")} fullScreen />;
  if (isError || !run) {
    return (
      <EmptyState
        icon={<Wallet className="h-5 w-5" />}
        title={t("payroll.run.notFound.title")}
        description={t("payroll.run.notFound.description")}
        action={
          <Button variant="outline" asChild>
            <Link to="/payroll/runs">{t("payroll.run.back")}</Link>
          </Button>
        }
      />
    );
  }

  const editable = run.status === "draft" || run.status === "calculated";
  // A regular run is calculated and approved only while the month's presence is closed.
  const presenceOpen = editable && run.presence_closed === false;
  // The server refuses the calculator's own approval; say so up front (the button still shows the refusal).
  const ownCalculation = run.status === "calculated" && run.calculated_by === session?.userId && hasPermission("payroll.approve_runs");

  // Refusals (SAME_USER_APPROVAL, RULESET_NOT_CONFIRMED, PRESENCE_NOT_CLOSED, PAYOUT_INCOMPLETE, ...)
  // arrive already worded in the user's language: toast them and keep them on the page.
  const refused = (titleKey: TranslationKey) => (error: unknown) => {
    const next = { title: t(titleKey), message: errorText(error) };
    setRefusal(next);
    toast.error(next.title, { description: next.message });
  };

  const onCalculate = () => {
    setRefusal(null);
    calculate.mutate(run.id, { onSuccess: () => toast.success(t("payroll.run.calculatedToast")), onError: refused("payroll.run.calculateRefused") });
  };
  const onApprove = () => {
    setRefusal(null);
    approve.mutate(run.id, { onSuccess: () => toast.success(t("payroll.run.approvedToast")), onError: refused("payroll.run.approveRefused") });
  };
  const onMarkPaid = () => {
    setRefusal(null);
    markPaid.mutate(run.id, { onSuccess: () => toast.success(t("payroll.run.markedPaidToast")), onError: refused("payroll.run.markPaidRefused") });
  };

  // The banner names the draft set the payslips came from; before a (re)calculation, the draft set it would use.
  const draftRuleSet =
    run.rule_set_id && run.rule_set_status === "draft"
      ? {
          id: run.rule_set_id,
          name: run.rule_set_in_force?.id === run.rule_set_id ? run.rule_set_in_force.name : (ownRuleSet?.name ?? run.rule_set_id),
          status: "draft",
        }
      : editable && run.rule_set_in_force?.status === "draft"
        ? run.rule_set_in_force
        : null;

  const summary: { label: string; value: string; warn?: boolean }[] = [
    { label: t("payroll.run.summary.payslips"), value: String(run.payslip_count) },
    { label: t("payroll.run.summary.gross"), value: formatXof(run.gross) },
    { label: t("payroll.run.summary.net"), value: formatXof(run.net) },
    { label: t("payroll.run.summary.employerCost"), value: formatXof(run.employer_cost) },
    { label: t("payroll.run.summary.warnings"), value: String(run.warning_count), warn: run.warning_count > 0 },
  ];

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/payroll/runs">
              <ArrowLeft className="h-4 w-4" />
              {t("payroll.run.back")}
            </Link>
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">
                {formatPeriod(run.period)} · {t(`payroll.runs.type.${run.run_type}` as TranslationKey)}
              </h1>
              <PayrollStatusBadge domain="run" status={run.status} />
            </div>
            {run.label && <p className="text-sm text-muted-foreground">{run.label}</p>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" asChild>
            <Link to="/payroll/inputs">
              <ListChecks className="h-4 w-4" />
              {t("payroll.run.inputsLink")}
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to={`/payroll/runs/${run.id}/print`}>
              <Printer className="h-4 w-4" />
              {t("payroll.run.print")}
            </Link>
          </Button>
          {editable && hasPermission("payroll.calculate_runs") && (
            <Button variant={run.status === "draft" ? "default" : "outline"} onClick={onCalculate} disabled={calculate.isPending}>
              <Calculator className="h-4 w-4" />
              {run.status === "draft" ? t("payroll.run.calculate") : t("payroll.run.recalculate")}
            </Button>
          )}
          {/* Never disabled for a rule the server enforces: a refusal is shown with its reason. */}
          {run.status === "calculated" && hasPermission("payroll.approve_runs") && (
            <Button onClick={onApprove} disabled={approve.isPending}>
              <BadgeCheck className="h-4 w-4" />
              {t("payroll.run.approve")}
            </Button>
          )}
          {run.status === "approved" && hasPermission("payroll.pay_runs") && (
            <Button onClick={onMarkPaid} disabled={markPaid.isPending}>
              <Banknote className="h-4 w-4" />
              {t("payroll.run.markPaid")}
            </Button>
          )}
          {(run.status === "approved" || run.status === "paid") && hasPermission("payroll.reverse_runs") && (
            <Button variant="outline" className="text-destructive" onClick={() => setReverseOpen(true)}>
              <Undo2 className="h-4 w-4" />
              {t("payroll.run.reverse")}
            </Button>
          )}
        </div>
      </motion.div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {summary.map((item) => (
          <div key={item.label} className="rounded-lg border border-border bg-background px-3 py-2">
            <dt className="text-xs text-muted-foreground">{item.label}</dt>
            <dd className={`text-sm font-semibold tabular-nums ${item.warn ? "text-warning" : ""}`}>{item.value}</dd>
          </div>
        ))}
      </dl>

      {(refusal || draftRuleSet || presenceOpen || ownCalculation || run.status === "reversed") && (
        <div className="space-y-2">
          {refusal && (
            <div role="alert" className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive-soft p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
              <div className="flex-1">
                <p className="font-medium text-destructive">{refusal.title}</p>
                <p className="text-foreground">{refusal.message}</p>
              </div>
              <button
                type="button"
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={t("payroll.run.dismiss")}
                onClick={() => setRefusal(null)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )}
          <DraftRuleSetBanner ruleSet={draftRuleSet} />
          {presenceOpen && (
            <p className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              {t("payroll.run.presenceNotClosed")}
            </p>
          )}
          {ownCalculation && (
            <p className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {t("payroll.run.ownCalculation")}
            </p>
          )}
          {run.status === "reversed" && (
            <p className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
              <Undo2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span>
                <span className="font-medium">{t("payroll.run.reversalReason")}</span> {run.reversal_reason ?? "—"}
              </span>
            </p>
          )}
        </div>
      )}

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
          <TabsList>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value} active={tab === entry.value} layoutId="payroll-run-tab">
                <span className="flex items-center gap-1.5">
                  <entry.icon className="h-4 w-4" />
                  {t(entry.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>

      {tab === "payslips" && <PayslipsPanel runId={run.id} />}
      {tab === "variance" && <div data-task="5-wires-VariancePanel-here" />}
      {/* Final settlements belong to off-cycle runs; on a regular run the panel says so. */}
      {tab === "settlements" && (
        <SettlementsPanel run={run} canEdit={hasPermission("payroll.calculate_runs")} />
      )}
      {tab === "payouts" && <div data-task="6-wires-PayoutsPanel-here" />}
      {tab === "declarations" && <div data-task="6-wires-DeclarationsPanel-here" />}

      <ReverseDialog open={reverseOpen} onOpenChange={setReverseOpen} runId={run.id} />
    </div>
  );
}
