import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Archive, ArrowDown, ArrowUp, Plus, RotateCcw, Trash } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { BUILT_IN_WASTE_CATEGORIES, createWasteType, updateWasteType, type ReportType, type WasteType } from "./api";
import { WASTE_TYPES_QUERY_KEY, useWasteTypes } from "./wasteTypes";
import { AppLoader } from "../../components/patterns/AppLoader";

const REPORTS: ReportType[] = ["daily", "conditionnement"];

/**
 * The déchet kinds a report offers: the built-in ones, which are always there and
 * whose names are translated, and the ones this plant adds — a name, and the one
 * report each is entered on.
 *
 * A kind is retired rather than deleted: a line stores its id, so removing it
 * would leave old reports saying something nobody can read. The report it is
 * entered on is fixed when it is created, because lines already filed under it
 * were checked against that report.
 */
export function WasteTypesCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { types, isLoading, label } = useWasteTypes();
  const [name, setName] = useState("");
  const [reportType, setReportType] = useState<ReportType>("daily");

  function ownFor(report: ReportType): WasteType[] {
    return types
      .filter((type) => type.report_type === report)
      .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
  }

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: WASTE_TYPES_QUERY_KEY });
  }

  function onError(error: unknown) {
    toast.error(t("production.settings.saveError"), {
      description: error instanceof ApiError ? error.message : undefined,
    });
  }

  const createMutation = useMutation({
    mutationFn: () => {
      const mine = ownFor(reportType);
      return createWasteType(token, {
        name,
        report_type: reportType,
        // New kinds go to the end of their report; the arrows are how they are ordered.
        sort_order: mine.length === 0 ? 1 : Math.max(...mine.map((type) => type.sort_order)) + 1,
      });
    },
    onSuccess: () => {
      invalidate();
      setName("");
      toast.success(t("production.settings.saved"));
    },
    onError,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, ...input }: { id: string; name?: string; sort_order?: number; is_active?: boolean }) =>
      updateWasteType(token, id, input),
    onSuccess: () => {
      invalidate();
      toast.success(t("production.settings.saved"));
    },
    onError,
  });

  /** Swap sort_order with the neighbour on the same report, which is what "move up" means here. */
  function move(type: WasteType, direction: -1 | 1) {
    const mine = ownFor(type.report_type);
    const neighbour = mine[mine.findIndex((entry) => entry.id === type.id) + direction];
    if (!neighbour) return;
    updateMutation.mutate({ id: type.id, sort_order: neighbour.sort_order });
    updateMutation.mutate({ id: neighbour.id, sort_order: type.sort_order });
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
          REPORTS.map((report) => {
            const own = ownFor(report);
            return (
              <section key={report} className="space-y-1.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t(`production.settings.wasteTypes.report.${report}` as TranslationKey)}
                </p>
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {BUILT_IN_WASTE_CATEGORIES[report].map((category) => (
                    <li key={category} className="flex items-center gap-2 p-2 text-sm">
                      <span className="flex-1 px-1">{label(category)}</span>
                      <Badge variant="outline">{t("production.settings.wasteTypes.builtIn")}</Badge>
                    </li>
                  ))}
                  <AnimatePresence initial={false}>
                    {own.map((type, index) => (
                      <motion.li
                        key={type.id}
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
                            onClick={() => move(type, -1)}
                          >
                            <ArrowUp className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            aria-label={t("production.settings.options.moveDown")}
                            className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
                            disabled={index === own.length - 1}
                            onClick={() => move(type, 1)}
                          >
                            <ArrowDown className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div className="min-w-0 flex-1">
                          <Input
                            defaultValue={type.name}
                            className={type.is_active ? undefined : "text-muted-foreground line-through"}
                            onBlur={(event) => {
                              const next = event.target.value.trim();
                              if (next && next !== type.name) updateMutation.mutate({ id: type.id, name: next });
                            }}
                          />
                        </div>
                        {!type.is_active && (
                          <Badge variant="outline">{t("production.settings.options.retiredBadge")}</Badge>
                        )}
                        {type.is_active ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={t("production.settings.wasteTypes.retire")}
                            onClick={() => updateMutation.mutate({ id: type.id, is_active: false })}
                          >
                            <Archive className="h-3.5 w-3.5" />
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={t("production.settings.options.restore")}
                            onClick={() => updateMutation.mutate({ id: type.id, is_active: true })}
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </motion.li>
                    ))}
                  </AnimatePresence>
                </ul>
                {own.length === 0 && (
                  <p className="px-1 text-xs text-muted-foreground">{t("production.settings.wasteTypes.empty")}</p>
                )}
              </section>
            );
          })
        )}

        <form
          className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) createMutation.mutate();
          }}
        >
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("production.settings.wasteTypes.namePlaceholder")}
            aria-label={t("production.settings.wasteTypes.namePlaceholder")}
          />
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
