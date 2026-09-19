import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import type { UseFormRegisterReturn } from "react-hook-form";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import {
  REPORT_OPTIONS_QUERY_KEY,
  createReportOption,
  listReportOptions,
  optionsFor,
  type ReportOptionKind,
} from "../../lib/reportOptions";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { DOWNTIME_CLASSIFICATIONS, DOWNTIME_MOTIFS, DOWNTIME_TYPES } from "./DowntimeMotifSelect";

/** The three questions an arrêt line asks. */
export type DowntimeField = "type" | "classification" | "motif";

/** Who is allowed to extend the lists — the same right that manages shifts and teams. */
export const MANAGE_DOWNTIME_OPTIONS_PERMISSION = "core.manage_report_options";

export const DOWNTIME_OPTION_KIND: Record<DowntimeField, ReportOptionKind> = {
  type: "downtime_type",
  classification: "downtime_classification",
  motif: "downtime_motif",
};

/**
 * What ships with the app. These are stored on a line as codes and translated
 * for display; whatever an admin adds is stored as the name they typed.
 */
const BUILT_IN: Record<DowntimeField, readonly string[]> = {
  type: DOWNTIME_TYPES,
  classification: DOWNTIME_CLASSIFICATIONS,
  motif: DOWNTIME_MOTIFS,
};

/**
 * What to show for a stored type, classification or motif.
 *
 * `t` hands the key itself back when it has no translation, which is exactly the
 * case for a value an admin added — so that is the signal to show the value as
 * typed rather than a raw translation key.
 */
export function downtimeLabel(t: (key: TranslationKey) => string, field: DowntimeField, value: string): string {
  const key = `production.downtime.${field}.${value}` as TranslationKey;
  const translated = t(key);
  return translated === key ? value : translated;
}

/**
 * The choices for one arrêt field: the built-in values, then the plant's own.
 *
 * The plant's additions sit before a trailing "Autre" so that stays the last
 * resort. A line that already carries a value the list no longer offers — one
 * that was retired, say — keeps it: opening an old report to edit it must not
 * silently blank the field, and saving it must not rewrite history.
 */
export function useDowntimeChoices(field: DowntimeField) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data: options = [] } = useQuery({
    queryKey: REPORT_OPTIONS_QUERY_KEY,
    queryFn: () => listReportOptions(session!.token),
  });

  return (current?: string | null, pending?: string | null): { value: string; label: string }[] => {
    const builtIn = BUILT_IN[field];
    const known = new Set(builtIn.map((value) => value.toLowerCase()));
    const custom = optionsFor(options, DOWNTIME_OPTION_KIND[field]).filter((label) => !known.has(label.toLowerCase()));
    const values = [
      ...builtIn.filter((value) => value !== "other"),
      ...custom,
      ...builtIn.filter((value) => value === "other"),
    ];
    for (const extra of [pending, current]) {
      if (extra && !values.includes(extra)) values.push(extra);
    }
    return values.map((value) => ({ value, label: downtimeLabel(t, field, value) }));
  };
}

/**
 * One arrêt dropdown: the label, the select, and — for someone allowed to
 * manage the lists — a "+" that adds a value without leaving the report.
 *
 * The select stays registered with the caller's form, so this drops into a row
 * in place of a bare `<Select>`. `onPick` is how a value the admin just added
 * gets selected: the select is uncontrolled, so the form has to be told.
 */
export function DowntimeOptionField({
  id,
  field,
  registration,
  current,
  onPick,
}: {
  id: string;
  field: DowntimeField;
  registration: UseFormRegisterReturn;
  /** What the line already says, so a retired value is never silently dropped. */
  current?: string | null;
  onPick: (value: string) => void;
}) {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const choices = useDowntimeChoices(field);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  // Select the new value only once it is an <option>: setting an uncontrolled
  // select to a value it does not yet list leaves it blank.
  useEffect(() => {
    if (pending === null) return;
    onPick(pending);
    setPending(null);
  }, [pending, onPick]);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-1">
        <Label htmlFor={id} className="text-xs">
          {t(`production.downtime.field.${field}` as TranslationKey)}
        </Label>
        {hasPermission(MANAGE_DOWNTIME_OPTIONS_PERMISSION) && (
          <button
            type="button"
            aria-label={t(`production.downtime.addOption.title.${field}` as TranslationKey)}
            title={t(`production.downtime.addOption.title.${field}` as TranslationKey)}
            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            onClick={() => setDialogOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <Select id={id} {...registration}>
        <option value="">—</option>
        {choices(current, pending).map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </Select>
      <AddDowntimeOptionDialog
        field={field}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onCreated={(label) => setPending(label)}
      />
    </div>
  );
}

function AddDowntimeOptionDialog({
  field,
  open,
  onOpenChange,
  onCreated,
}: {
  field: DowntimeField;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (label: string) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const kind = DOWNTIME_OPTION_KIND[field];

  const { data: options = [] } = useQuery({
    queryKey: [...REPORT_OPTIONS_QUERY_KEY, "all"],
    queryFn: () => listReportOptions(token, true),
  });

  const mutation = useMutation({
    mutationFn: () => {
      const orders = options.filter((option) => option.kind === kind).map((option) => option.sort_order);
      // New entries go to the end, the way the settings screen adds them.
      return createReportOption(token, { kind, label, sort_order: orders.length === 0 ? 1 : Math.max(...orders) + 1 });
    },
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: REPORT_OPTIONS_QUERY_KEY });
      toast.success(t("production.downtime.addOption.saved"));
      setLabel("");
      onOpenChange(false);
      onCreated(created.label);
    },
    onError: (error) => {
      toast.error(t("production.settings.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  function submit() {
    if (label.trim() && !mutation.isPending) mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(`production.downtime.addOption.title.${field}` as TranslationKey)}</DialogTitle>
          <DialogDescription>{t("production.downtime.addOption.description")}</DialogDescription>
        </DialogHeader>
        {/*
          Deliberately not a <form>: this dialog is portalled out of the report
          form's DOM, but React still bubbles its events up through it, so a
          submit here would file the report underneath.
        */}
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor={`new_downtime_${field}`}>{t("production.downtime.addOption.label")}</Label>
            <Input
              id={`new_downtime_${field}`}
              value={label}
              autoFocus
              onChange={(event) => setLabel(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                event.stopPropagation();
                submit();
              }}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="button" size="sm" disabled={!label.trim() || mutation.isPending} onClick={submit}>
              {mutation.isPending ? t("common.saving") : t("common.add")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
