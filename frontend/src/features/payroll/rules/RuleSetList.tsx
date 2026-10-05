import { useState } from "react";
import { toast } from "sonner";
import { ChevronRight, Copy, Lock, LockOpen, Pencil, Plus, ScrollText, Trash2 } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { cn } from "../../../lib/utils";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { useConfirmRuleSet, useDeleteRuleSet, useReopenRuleSet, useRuleSets, type RuleSetHeader, type RuleSetStatus } from "../api";
import { formatPeriod } from "../format";
import { PayrollTable } from "../PayrollTable";

type StatusFilter = "all" | RuleSetStatus;

export function RuleSetStatusBadge({ status }: { status: RuleSetStatus }) {
  const { t } = useI18n();
  return <Badge variant={status === "confirmed" ? "success" : "outline"}>{t(`payroll.status.ruleSet.${status}`)}</Badge>;
}

/** Confirm / reopen / delete, each reporting the outcome (a refusal names why, in the user's language). */
export function useRuleSetCommands({ onDeleted }: { onDeleted?: (id: string) => void } = {}) {
  const { t } = useI18n();
  const confirmMutation = useConfirmRuleSet();
  const reopenMutation = useReopenRuleSet();
  const deleteMutation = useDeleteRuleSet();
  const refused = (error: Error) => toast.error(t("payroll.rules.actionFailed"), { description: error.message });
  return {
    pending: confirmMutation.isPending || reopenMutation.isPending || deleteMutation.isPending,
    confirm: (id: string) =>
      confirmMutation.mutate(id, { onSuccess: () => toast.success(t("payroll.rules.ruleSets.confirmed")), onError: refused }),
    reopen: (id: string) =>
      reopenMutation.mutate(id, { onSuccess: () => toast.success(t("payroll.rules.ruleSets.reopened")), onError: refused }),
    remove: (id: string) => {
      if (!window.confirm(t("payroll.rules.ruleSets.deleteConfirm"))) return;
      deleteMutation.mutate(id, {
        onSuccess: () => {
          toast.success(t("payroll.rules.ruleSets.deleted"));
          onDeleted?.(id);
        },
        onError: refused,
      });
    },
  };
}

export function RuleSetList({
  selectedId,
  onSelect,
  onNew,
  onEdit,
  onCopy,
  onDeleted,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onEdit: (ruleSet: RuleSetHeader) => void;
  onCopy: (ruleSet: RuleSetHeader) => void;
  onDeleted: (id: string) => void;
}) {
  const { t, language } = useI18n();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("payroll.manage_rules");
  const canConfirm = hasPermission("payroll.confirm_rules");
  const { data: ruleSets = [], isLoading } = useRuleSets();
  const commands = useRuleSetCommands({ onDeleted });
  const [status, setStatus] = useState<StatusFilter>("all");
  const locale = language === "fr" ? "fr-FR" : "en-US";
  const filters = useColumnFilters<RuleSetHeader>([
    { key: "name", kind: "text", getValue: (row) => row.name },
    { key: "country", kind: "text", getValue: (row) => row.country },
    { key: "validFrom", kind: "text", getValue: (row) => formatPeriod(row.valid_from, locale) },
  ]);
  const textFilter = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });

  const actionsFor = (row: RuleSetHeader): RowAction[] => {
    const draft = row.status === "draft";
    const actions: RowAction[] = [];
    if (draft && canManage)
      actions.push({ key: "edit", label: t("payroll.rules.ruleSets.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => onEdit(row) });
    if (draft && canConfirm)
      actions.push({
        key: "confirm",
        label: t("payroll.rules.ruleSets.confirm"),
        icon: <Lock className="h-3.5 w-3.5" />,
        disabled: commands.pending,
        onSelect: () => commands.confirm(row.id),
      });
    if (!draft && canConfirm)
      actions.push({
        key: "reopen",
        label: t("payroll.rules.ruleSets.reopen"),
        icon: <LockOpen className="h-3.5 w-3.5" />,
        disabled: commands.pending,
        onSelect: () => commands.reopen(row.id),
      });
    if (canManage)
      actions.push({ key: "copy", label: t("payroll.rules.ruleSets.copy"), icon: <Copy className="h-3.5 w-3.5" />, onSelect: () => onCopy(row) });
    if (draft && canManage)
      actions.push({
        key: "delete",
        label: t("payroll.rules.ruleSets.delete"),
        icon: <Trash2 className="h-3.5 w-3.5" />,
        tone: "destructive",
        disabled: commands.pending,
        onSelect: () => commands.remove(row.id),
      });
    return actions;
  };

  const columns: ColumnDef<RuleSetHeader>[] = [
    {
      key: "name",
      header: t("payroll.rules.ruleSets.name"),
      defaultWidth: 260,
      sortValue: (row) => row.name,
      filterCell: textFilter("name", t("payroll.rules.ruleSets.name")),
      cell: (row) => {
        const selected = row.id === selectedId;
        return (
          <span className={cn("flex items-center gap-1.5", selected && "font-medium text-primary")}>
            <ChevronRight className={cn("h-3.5 w-3.5 shrink-0", selected ? "text-primary" : "text-transparent")} aria-hidden />
            <span className="truncate">{row.name}</span>
          </span>
        );
      },
    },
    {
      key: "country",
      header: t("payroll.rules.ruleSets.country"),
      defaultWidth: 110,
      sortValue: (row) => row.country,
      filterCell: textFilter("country", t("payroll.rules.ruleSets.country")),
      cell: (row) => row.country,
    },
    {
      key: "validFrom",
      header: t("payroll.rules.ruleSets.validFrom"),
      defaultWidth: 180,
      sortValue: (row) => row.valid_from,
      filterCell: textFilter("validFrom", t("payroll.rules.ruleSets.validFrom")),
      cell: (row) => <span className="capitalize">{formatPeriod(row.valid_from, locale)}</span>,
    },
    {
      key: "status",
      header: t("payroll.rules.ruleSets.status"),
      defaultWidth: 130,
      sortValue: (row) => row.status,
      filterCell: { type: "blank" },
      cell: (row) => <RuleSetStatusBadge status={row.status} />,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 72,
      alwaysVisible: true,
      cellClassName: "text-right",
      filterCell: { type: "blank" },
      cell: (row) => <RowActionsMenu actions={actionsFor(row)} />,
    },
  ];

  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    { value: "draft", label: t("payroll.status.ruleSet.draft") },
    { value: "confirmed", label: t("payroll.status.ruleSet.confirmed") },
  ];
  const rows = filters.apply(status === "all" ? ruleSets : ruleSets.filter((row) => row.status === status));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("payroll.rules.ruleSets.title")}</CardTitle>
        {canManage && (
          <Button onClick={onNew}>
            <Plus className="h-4 w-4" />
            {t("payroll.rules.ruleSets.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <PayrollTable
          tableKey="payroll.rules.ruleSets"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          loading={isLoading}
          emptyTitle={t("payroll.rules.ruleSets.empty.title")}
          emptyDescription={t("payroll.rules.ruleSets.empty.description")}
          emptyIcon={<ScrollText className="h-5 w-5" />}
          toolbar={<FilterTabs options={statusOptions} value={status} onChange={setStatus} />}
          filtersActive={status !== "all" || filters.isActive}
          onClearFilters={() => {
            setStatus("all");
            filters.reset();
          }}
          onRowClick={(row) => onSelect(row.id)}
        />
      </CardContent>
    </Card>
  );
}
