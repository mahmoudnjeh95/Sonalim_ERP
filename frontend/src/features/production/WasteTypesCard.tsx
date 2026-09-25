import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Reorder, useDragControls } from "framer-motion";
import { ArrowDown, ArrowUp, EyeOff, GripVertical, Plus, RotateCcw, Trash, Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { cn } from "../../lib/utils";
import {
  createWasteType,
  deleteWasteType,
  reorderWasteTypes,
  updateBuiltInWasteType,
  updateWasteType,
  type ReportType,
  type WasteCategory,
} from "./api";
import { WASTE_TYPES_QUERY_KEY, useWasteTypes, type WasteTypeEntry } from "./wasteTypes";
import { AppLoader } from "../../components/patterns/AppLoader";

const REPORTS: ReportType[] = ["daily", "conditionnement"];

/**
 * The déchet kinds each report offers, built-in and the plant's own in one list:
 * rename any of them in place, drag them into order, take them off the forms.
 *
 * A built-in cannot be deleted — it lives in code and the day sheet reasons about
 * it — so its "remove" hides it and it can be put back. A plant kind is deleted,
 * or retired when a report already has a line under it: a line stores its id,
 * and removing the row would leave old reports saying something nobody can read.
 * The report a kind is entered on is fixed when it is created, because lines
 * already filed under it were checked against that report.
 */
export function WasteTypesCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { isLoading, entriesFor } = useWasteTypes();
  const [name, setName] = useState("");
  const [reportType, setReportType] = useState<ReportType>("daily");

  function invalidate() {
    return queryClient.invalidateQueries({ queryKey: WASTE_TYPES_QUERY_KEY });
  }

  function onError(error: unknown) {
    toast.error(t("production.settings.saveError"), {
      description: error instanceof ApiError ? error.message : undefined,
    });
    invalidate();
  }

  function onSaved() {
    invalidate();
    toast.success(t("production.settings.saved"));
  }

  const createMutation = useMutation({
    mutationFn: () =>
      // New kinds go to the end of their report's list.
      createWasteType(token, { name, report_type: reportType, sort_order: 10_000 }),
    onSuccess: () => {
      setName("");
      onSaved();
    },
    onError,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      entry,
      ...input
    }: {
      entry: WasteTypeEntry;
      name?: string;
      reset_name?: boolean;
      is_active?: boolean;
    }): Promise<unknown> =>
      entry.builtIn
        ? updateBuiltInWasteType(token, entry.key, input)
        : updateWasteType(token, entry.key, { name: input.name, is_active: input.is_active }),
    onSuccess: onSaved,
    onError,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteWasteType(token, id),
    onSuccess: (result) => {
      invalidate();
      // Deleting and retiring are different outcomes: a retired kind is still on old reports.
      toast.success(
        result.outcome === "retired"
          ? t("production.settings.wasteTypes.retired")
          : t("production.settings.options.deleted"),
      );
    },
    onError,
  });

  const reorderMutation = useMutation({
    mutationFn: ({ report, order }: { report: ReportType; order: WasteCategory[] }) =>
      reorderWasteTypes(token, report, order),
    onSuccess: onSaved,
    onError,
  });

  function rename(entry: WasteTypeEntry, value: string) {
    const next = value.trim();
    if (next === entry.label) return;
    if (entry.builtIn) {
      // Cleared, or typed back to the original: that is the translated default again.
      if (!next || next === entry.defaultLabel) {
        if (entry.renamed) updateMutation.mutate({ entry, reset_name: true });
        return;
      }
      updateMutation.mutate({ entry, name: next });
    } else if (next) {
      updateMutation.mutate({ entry, name: next });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5 text-base">
          <Trash className="h-4 w-4" />
          {t("production.settings.wasteTypes.title")}
        </CardTitle>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("production.settings.wasteTypes.description")}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : (
          REPORTS.map((report) => (
            <section key={report} className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t(`production.settings.wasteTypes.report.${report}` as TranslationKey)}
              </p>
              <ReportList
                entries={entriesFor(report)}
                onReorder={(order) => reorderMutation.mutate({ report, order })}
                onRename={rename}
                onSetActive={(entry, is_active) => updateMutation.mutate({ entry, is_active })}
                onResetName={(entry) => updateMutation.mutate({ entry, reset_name: true })}
                onDelete={(entry) => deleteMutation.mutate(entry.key)}
              />
            </section>
          ))
        )}

        <form
          className="flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) createMutation.mutate();
          }}
        >
          <div className="min-w-48 flex-[2_1_12rem]">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("production.settings.wasteTypes.namePlaceholder")}
              aria-label={t("production.settings.wasteTypes.namePlaceholder")}
            />
          </div>
          <div className="min-w-0 flex-[1_1_10rem]">
            <Select
              value={reportType}
              onChange={(event) => setReportType(event.target.value as ReportType)}
              aria-label={t("production.settings.wasteTypes.enteredOn")}
            >
              {REPORTS.map((report) => (
                <option key={report} value={report}>
                  {t(`production.settings.wasteTypes.report.${report}` as TranslationKey)}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" size="sm" disabled={!name.trim() || createMutation.isPending}>
            <Plus className="h-3.5 w-3.5" />
            {t("common.add")}
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">{t("production.settings.wasteTypes.help")}</p>
      </CardContent>
    </Card>
  );
}

interface RowActions {
  onRename: (entry: WasteTypeEntry, value: string) => void;
  onSetActive: (entry: WasteTypeEntry, isActive: boolean) => void;
  onResetName: (entry: WasteTypeEntry) => void;
  onDelete: (entry: WasteTypeEntry) => void;
}

/**
 * One report's kinds. The order is held locally while a row is dragged and sent
 * once it is dropped, so the list does not jump back between the drop and the
 * server's answer.
 */
function ReportList({
  entries,
  onReorder,
  ...actions
}: { entries: WasteTypeEntry[]; onReorder: (order: WasteCategory[]) => void } & RowActions) {
  const serverOrder = entries.map((entry) => entry.key);
  const serverKey = serverOrder.join("|");
  const [order, setOrder] = useState(serverOrder);
  useEffect(() => setOrder(serverKey.split("|")), [serverKey]);

  const byKey = new Map(entries.map((entry) => [entry.key, entry]));
  const shown = order.filter((key) => byKey.has(key));

  function commit(next: WasteCategory[]) {
    if (next.join("|") !== serverKey) onReorder(next);
  }

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= shown.length) return;
    const next = [...shown];
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
    commit(next);
  }

  return (
    <Reorder.Group
      axis="y"
      values={shown}
      onReorder={setOrder}
      className="divide-y divide-border rounded-lg border border-border"
    >
      {shown.map((key, index) => (
        <Row
          key={key}
          entry={byKey.get(key)!}
          isFirst={index === 0}
          isLast={index === shown.length - 1}
          onMove={(direction) => move(index, direction)}
          onDrop={() => commit(shown)}
          {...actions}
        />
      ))}
    </Reorder.Group>
  );
}

function Row({
  entry,
  isFirst,
  isLast,
  onMove,
  onDrop,
  onRename,
  onSetActive,
  onResetName,
  onDelete,
}: {
  entry: WasteTypeEntry;
  isFirst: boolean;
  isLast: boolean;
  onMove: (direction: -1 | 1) => void;
  onDrop: () => void;
} & RowActions) {
  const { t } = useI18n();
  const controls = useDragControls();

  return (
    <Reorder.Item
      value={entry.key}
      dragListener={false}
      dragControls={controls}
      onDragEnd={onDrop}
      className="flex items-center gap-2 bg-background p-2 first:rounded-t-lg last:rounded-b-lg"
    >
      <button
        type="button"
        aria-label={t("production.settings.wasteTypes.dragHandle")}
        title={t("production.settings.wasteTypes.dragHandle")}
        className="cursor-grab touch-none text-muted-foreground transition-colors hover:text-foreground active:cursor-grabbing"
        onPointerDown={(event) => controls.start(event)}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <div className="flex flex-col">
        <button
          type="button"
          aria-label={t("production.settings.options.moveUp")}
          className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
          disabled={isFirst}
          onClick={() => onMove(-1)}
        >
          <ArrowUp className="h-3 w-3" />
        </button>
        <button
          type="button"
          aria-label={t("production.settings.options.moveDown")}
          className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
          disabled={isLast}
          onClick={() => onMove(1)}
        >
          <ArrowDown className="h-3 w-3" />
        </button>
      </div>
      <div className="min-w-0 flex-1">
        <Input
          // Re-mounted when the saved name changes, so a reset shows up in the field.
          key={entry.label}
          defaultValue={entry.label}
          placeholder={entry.defaultLabel ?? undefined}
          className={cn("h-8", !entry.is_active && "text-muted-foreground line-through")}
          onBlur={(event) => onRename(entry, event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              event.currentTarget.value = entry.label;
              event.currentTarget.blur();
            }
          }}
        />
      </div>
      {entry.builtIn && (
        <Badge variant="outline" title={entry.renamed ? entry.defaultLabel ?? undefined : undefined}>
          {t("production.settings.wasteTypes.builtIn")}
        </Badge>
      )}
      {!entry.is_active && <Badge variant="outline">{t("production.settings.options.retiredBadge")}</Badge>}
      {entry.builtIn && entry.renamed && (
        <Button
          size="sm"
          variant="ghost"
          aria-label={t("production.settings.wasteTypes.resetName")}
          title={`${t("production.settings.wasteTypes.resetName")} — ${entry.defaultLabel}`}
          onClick={() => onResetName(entry)}
        >
          <Undo2 className="h-3.5 w-3.5" />
        </Button>
      )}
      {!entry.is_active ? (
        <Button
          size="sm"
          variant="ghost"
          aria-label={t("production.settings.options.restore")}
          title={t("production.settings.options.restore")}
          onClick={() => onSetActive(entry, true)}
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>
      ) : entry.builtIn ? (
        <Button
          size="sm"
          variant="ghost"
          aria-label={t("production.settings.wasteTypes.hide")}
          title={t("production.settings.wasteTypes.hide")}
          onClick={() => onSetActive(entry, false)}
        >
          <EyeOff className="h-3.5 w-3.5" />
        </Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          aria-label={t("common.delete")}
          title={t("common.delete")}
          className="text-muted-foreground hover:text-destructive"
          onClick={() => onDelete(entry)}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      )}
    </Reorder.Item>
  );
}
