import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Copy, Lock, LockOpen, Pencil, ScrollText, SearchX } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { usePayrollSettings, useRuleSet, useRuleSets, type RuleSetDocument, type RuleSetHeader } from "../api";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";
import { formatPeriod } from "../format";
import { CopyRuleSetDialog } from "./CopyRuleSetDialog";
import { RuleRowsTable } from "./RuleRowsTable";
import { RuleSetDialog } from "./RuleSetDialog";
import { RuleSetList, RuleSetStatusBadge, useRuleSetCommands } from "./RuleSetList";
import { SettingsCard } from "./SettingsCard";

type DialogState = { type: "new" } | { type: "edit"; ruleSet: RuleSetHeader } | { type: "copy"; ruleSet: RuleSetHeader } | null;

/** /payroll/rules — the payroll country, the rule sets, and the rows of the one picked (?ruleSet=<id>). */
export function RulesPage() {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("payroll.rules.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("payroll.rules.subtitle")}</p>
      </motion.div>
      {hasPermission("payroll.view_rules") ? (
        <RulesContent />
      ) : (
        <EmptyState icon={<ScrollText className="h-5 w-5" />} title={t("payroll.rules.noAccess.title")} description={t("payroll.rules.noAccess.description")} />
      )}
    </div>
  );
}

function RulesContent() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("ruleSet");
  const settings = usePayrollSettings();
  const ruleSets = useRuleSets();
  const [dialog, setDialog] = useState<DialogState>(null);
  // One branded loader for the screen's first load; the blocks stay mounted (hidden) behind it.
  const [booted, setBooted] = useState(false);
  const firstLoadDone = !settings.isLoading && !ruleSets.isLoading;
  useEffect(() => {
    if (firstLoadDone) setBooted(true);
  }, [firstLoadDone]);

  const select = (id: string | null) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (id) next.set("ruleSet", id);
        else next.delete("ruleSet");
        return next;
      },
      { replace: true },
    );
  const selectSaved = (saved: RuleSetDocument) => select(saved.id);

  return (
    <>
      {!booted && <AppLoader label={t("payroll.common.loading")} className="py-16" />}
      <div className={booted ? "space-y-6" : "hidden"}>
        <SettingsCard />
        <RuleSetList
          selectedId={selectedId}
          onSelect={select}
          onNew={() => setDialog({ type: "new" })}
          onEdit={(ruleSet) => setDialog({ type: "edit", ruleSet })}
          onCopy={(ruleSet) => setDialog({ type: "copy", ruleSet })}
          onDeleted={(id) => id === selectedId && select(null)}
        />
        {selectedId ? (
          <SelectedRuleSet
            id={selectedId}
            onEdit={(ruleSet) => setDialog({ type: "edit", ruleSet })}
            onCopy={(ruleSet) => setDialog({ type: "copy", ruleSet })}
          />
        ) : (
          (ruleSets.data?.length ?? 0) > 0 && <p className="text-sm text-muted-foreground">{t("payroll.rules.ruleSets.selectHint")}</p>
        )}
      </div>
      <RuleSetDialog
        open={dialog?.type === "new" || dialog?.type === "edit"}
        onOpenChange={(open) => !open && setDialog(null)}
        ruleSet={dialog?.type === "edit" ? dialog.ruleSet : undefined}
        onSaved={selectSaved}
      />
      {dialog?.type === "copy" && (
        <CopyRuleSetDialog open onOpenChange={(open) => !open && setDialog(null)} ruleSet={dialog.ruleSet} onCopied={selectSaved} />
      )}
    </>
  );
}

function SelectedRuleSet({
  id,
  onEdit,
  onCopy,
}: {
  id: string;
  onEdit: (ruleSet: RuleSetHeader) => void;
  onCopy: (ruleSet: RuleSetHeader) => void;
}) {
  const { t, language } = useI18n();
  const { hasPermission } = useAuth();
  const { data: ruleSet, isError } = useRuleSet(id);
  const commands = useRuleSetCommands();
  const canManage = hasPermission("payroll.manage_rules");
  const canConfirm = hasPermission("payroll.confirm_rules");
  const locale = language === "fr" ? "fr-FR" : "en-US";

  // A failed refetch keeps showing the rule set already loaded; only a first load that failed is "not found".
  if (!ruleSet && !isError) return <Skeleton className="h-80 w-full rounded-xl" />;
  if (!ruleSet)
    return (
      <Card>
        <EmptyState
          icon={<SearchX className="h-5 w-5" />}
          title={t("payroll.rules.ruleSets.notFound.title")}
          description={t("payroll.rules.ruleSets.notFound.description")}
        />
      </Card>
    );

  const draft = ruleSet.status === "draft";
  const number = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
  const facts: { labelKey: TranslationKey; value: ReactNode }[] = [
    { labelKey: "payroll.ruleSetForm.workingDays", value: number(ruleSet.working_days_per_month) },
    { labelKey: "payroll.ruleSetForm.workingHours", value: number(ruleSet.working_hours_per_month) },
    {
      labelKey: "payroll.ruleSetForm.roundTo",
      value: `${number(ruleSet.round_to)} · ${t(`payroll.ruleSetForm.roundMode.${ruleSet.round_mode}`)}`,
    },
    {
      labelKey: "payroll.ruleSetForm.taxRoundTo",
      value: `${number(ruleSet.tax_round_to)} · ${t(`payroll.ruleSetForm.roundMode.${ruleSet.tax_round_mode}`)}`,
    },
    { labelKey: "payroll.ruleSetForm.settlementReferenceMonths", value: number(ruleSet.settlement_reference_months) },
    { labelKey: "payroll.ruleSetForm.dailyRestDayPay", value: t(`payroll.ruleSetForm.dailyRestDayPay.${ruleSet.daily_rest_day_pay}`) },
  ];

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold tracking-tight">{ruleSet.name}</h2>
            <RuleSetStatusBadge status={ruleSet.status} />
          </div>
          <p className="text-sm capitalize text-muted-foreground">
            {ruleSet.country} · {formatPeriod(ruleSet.valid_from, locale)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {draft && canManage && (
            <Button variant="outline" size="sm" onClick={() => onEdit(ruleSet)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("payroll.rules.ruleSets.edit")}
            </Button>
          )}
          {canManage && (
            <Button variant="outline" size="sm" onClick={() => onCopy(ruleSet)}>
              <Copy className="h-3.5 w-3.5" />
              {t("payroll.rules.ruleSets.copy")}
            </Button>
          )}
          {draft && canConfirm && (
            <Button size="sm" disabled={commands.pending} onClick={() => commands.confirm(ruleSet.id)}>
              <Lock className="h-3.5 w-3.5" />
              {t("payroll.rules.ruleSets.confirm")}
            </Button>
          )}
          {!draft && canConfirm && (
            <Button variant="outline" size="sm" disabled={commands.pending} onClick={() => commands.reopen(ruleSet.id)}>
              <LockOpen className="h-3.5 w-3.5" />
              {t("payroll.rules.ruleSets.reopen")}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* No link: this is the page it would link to. */}
        <DraftRuleSetBanner ruleSet={{ id: "", name: ruleSet.name, status: ruleSet.status }} />
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          {facts.map((fact) => (
            <div key={fact.labelKey} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{t(fact.labelKey)}</dt>
              <dd className="text-sm font-medium tabular-nums">{fact.value}</dd>
            </div>
          ))}
          {ruleSet.notes && (
            <div className="min-w-0 sm:col-span-2 lg:col-span-3">
              <dt className="text-xs text-muted-foreground">{t("payroll.ruleSetForm.notes")}</dt>
              <dd className="whitespace-pre-line text-sm">{ruleSet.notes}</dd>
            </div>
          )}
        </dl>
        {!draft && <p className="text-sm text-muted-foreground">{t("payroll.rules.rows.locked")}</p>}
        <RuleRowsTable ruleSet={ruleSet} editable={draft && canManage} />
      </CardContent>
    </Card>
  );
}
