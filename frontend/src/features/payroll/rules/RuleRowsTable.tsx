import { useState } from "react";
import { toast } from "sonner";
import { Check, ListOrdered, Pencil, Plus, Trash2 } from "lucide-react";
import { useI18n } from "../../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { FilterCell } from "../../../components/patterns/ColumnFilterRow";
import { RowActionsMenu } from "../../../components/patterns/RowActionsMenu";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { RULE_ROW_KINDS, useDeleteRuleRow, type RuleRow, type RuleRowKind, type RuleSetDocument } from "../api";
import { formatXof } from "../format";
import { PayrollTable } from "../PayrollTable";
import { RuleRowDialog } from "./RuleRowDialog";
import { kindLabelKey, optionLabelKey, RULE_ROW_FIELDS, type RuleRowField } from "./ruleTables";

function numberValue(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function KindTable({ ruleSetId, kind, rows, editable }: { ruleSetId: string; kind: RuleRowKind; rows: RuleRow[]; editable: boolean }) {
  const { t, language } = useI18n();
  const locale = language === "fr" ? "fr-FR" : "en-US";
  const remove = useDeleteRuleRow(ruleSetId, kind);
  const [dialog, setDialog] = useState<{ open: boolean; row?: RuleRow }>({ open: false });
  const fields = RULE_ROW_FIELDS[kind];

  const display = (field: RuleRowField, row: RuleRow): string => {
    const value = row[field.name];
    if (field.kind === "select") return typeof value === "string" && value ? t(optionLabelKey(value)) : "—";
    if (field.kind === "json") return value === null || value === undefined ? "—" : JSON.stringify(value);
    if (field.kind === "money") return formatXof(numberValue(value), locale);
    if (field.kind === "number" || field.kind === "percent") {
      const number = numberValue(value);
      if (number === null) return "—";
      const formatted = new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(number);
      return field.kind === "percent" ? `${formatted} %` : formatted;
    }
    return value === null || value === undefined || value === "" ? "—" : String(value);
  };

  const filterFields: FilterField<RuleRow>[] = fields.flatMap((field): FilterField<RuleRow>[] => {
    if (field.kind === "boolean" || field.kind === "json") return [];
    if (field.kind === "text" || field.kind === "select") return [{ key: field.name, kind: "text", getValue: (row) => display(field, row) }];
    return [{ key: field.name, kind: "range", getValue: (row) => numberValue(row[field.name]) }];
  });
  const filters = useColumnFilters<RuleRow>(filterFields);

  const filterCellFor = (field: RuleRowField): FilterCell => {
    if (field.kind === "boolean" || field.kind === "json") return { type: "blank" };
    if (field.kind === "text" || field.kind === "select")
      return {
        type: "text",
        value: filters.text[field.name] ?? "",
        onChange: (value) => filters.setTextValue(field.name, value),
        placeholder: t(field.labelKey),
      };
    return {
      type: "range",
      min: filters.range[field.name]?.min ?? "",
      max: filters.range[field.name]?.max ?? "",
      onMinChange: (value) => filters.setRangeValue(field.name, "min", value),
      onMaxChange: (value) => filters.setRangeValue(field.name, "max", value),
    };
  };

  const deleteRow = (row: RuleRow) => {
    if (!window.confirm(t("payroll.ruleRow.deleteConfirm"))) return;
    remove.mutate(row.id, {
      onSuccess: () => toast.success(t("payroll.ruleRow.deleted")),
      onError: (error) => toast.error(t("payroll.rules.actionFailed"), { description: error.message }),
    });
  };

  const columns: ColumnDef<RuleRow>[] = fields.map((field) => ({
    key: field.name,
    header: t(field.labelKey),
    defaultWidth: field.kind === "json" ? 320 : field.kind === "boolean" ? 120 : 150,
    cellClassName: field.kind === "money" || field.kind === "number" || field.kind === "percent" ? "tabular-nums" : undefined,
    filterCell: filterCellFor(field),
    sortValue: field.kind === "json" ? undefined : (row) => (field.kind === "boolean" ? row[field.name] === true : (row[field.name] as string | number | null)),
    cell: (row) =>
      field.kind === "boolean" ? (
        row[field.name] === true ? <Check className="h-4 w-4 text-success" aria-label={t("common.yes")} /> : <span className="text-muted-foreground">—</span>
      ) : field.kind === "json" ? (
        <code className="block truncate text-xs">{display(field, row)}</code>
      ) : (
        display(field, row)
      ),
  }));
  if (editable)
    columns.push({
      key: "actions",
      header: "",
      defaultWidth: 72,
      alwaysVisible: true,
      cellClassName: "text-right",
      filterCell: { type: "blank" },
      cell: (row) => (
        <RowActionsMenu
          actions={[
            { key: "edit", label: t("common.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => setDialog({ open: true, row }) },
            {
              key: "delete",
              label: t("common.delete"),
              icon: <Trash2 className="h-3.5 w-3.5" />,
              tone: "destructive",
              disabled: remove.isPending,
              onSelect: () => deleteRow(row),
            },
          ]}
        />
      ),
    });

  return (
    <>
      <PayrollTable
        tableKey={`payroll.rules.rows.${kind}`}
        columns={columns}
        rows={filters.apply(rows)}
        rowKey={(row) => row.id}
        loading={false}
        emptyTitle={t("payroll.rules.rows.empty.title")}
        emptyDescription={t("payroll.rules.rows.empty.description")}
        emptyIcon={<ListOrdered className="h-5 w-5" />}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          editable && (
            <Button size="sm" onClick={() => setDialog({ open: true })}>
              <Plus className="h-4 w-4" />
              {t("payroll.rules.rows.add")}
            </Button>
          )
        }
      />
      <RuleRowDialog
        open={dialog.open}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
        ruleSetId={ruleSetId}
        kind={kind}
        row={dialog.row}
      />
    </>
  );
}

/** The seven rule tables of one rule set, one tab each; rows come with the rule set document. */
export function RuleRowsTable({ ruleSet, editable }: { ruleSet: RuleSetDocument; editable: boolean }) {
  const { t } = useI18n();
  const [kind, setKind] = useState<RuleRowKind>(RULE_ROW_KINDS[0]);
  return (
    <Tabs value={kind} onValueChange={(value) => setKind(value as RuleRowKind)} className="space-y-3">
      <TabsList>
        {RULE_ROW_KINDS.map((entry) => (
          <TabsTrigger key={entry} value={entry} active={kind === entry} layoutId="payroll-rule-rows-tab">
            <span className="flex items-center gap-1.5">
              {t(kindLabelKey(entry))}
              <span className="rounded-full bg-muted px-1.5 text-[11px] tabular-nums text-muted-foreground">{ruleSet[entry].length}</span>
            </span>
          </TabsTrigger>
        ))}
      </TabsList>
      {RULE_ROW_KINDS.map((entry) => (
        <TabsContent key={entry} value={entry}>
          <KindTable ruleSetId={ruleSet.id} kind={entry} rows={ruleSet[entry]} editable={editable} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
