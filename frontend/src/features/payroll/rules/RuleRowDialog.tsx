import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { FormField } from "../../hr/FormField";
import { useAddRuleRow, useUpdateRuleRow, type RuleRow, type RuleRowKind } from "../api";
import { kindLabelKey, optionLabelKey, RULE_ROW_FIELDS, type RuleRowField } from "./ruleTables";

type Values = Record<string, string | boolean>;

function initialValues(fields: RuleRowField[], row: RuleRow | undefined): Values {
  // A new row starts empty (unticked, no number): nothing is suggested.
  return Object.fromEntries(
    fields.map((field) => {
      const raw = row?.[field.name];
      if (field.kind === "boolean") return [field.name, raw === true];
      if (raw === null || raw === undefined) return [field.name, ""];
      if (field.kind === "json") return [field.name, JSON.stringify(raw, null, 2)];
      return [field.name, String(raw)];
    }),
  );
}

/** Add a row to one rule table of a draft rule set, or edit one; the server validates every value. */
export function RuleRowDialog({
  open,
  onOpenChange,
  ruleSetId,
  kind,
  row,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ruleSetId: string;
  kind: RuleRowKind;
  row?: RuleRow;
}) {
  const { t } = useI18n();
  const add = useAddRuleRow(ruleSetId, kind);
  const update = useUpdateRuleRow(ruleSetId, kind);
  const fields = RULE_ROW_FIELDS[kind];
  const [values, setValues] = useState<Values>(() => initialValues(fields, row));
  const [jsonError, setJsonError] = useState<string | null>(null);
  const pending = add.isPending || update.isPending;

  useEffect(() => {
    if (open) {
      setValues(initialValues(fields, row));
      setJsonError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind, row?.id]);

  const setValue = (name: string, value: string | boolean) => setValues((current) => ({ ...current, [name]: value }));

  const submit = () => {
    const body: Record<string, unknown> = {};
    for (const field of fields) {
      const raw = values[field.name];
      if (field.kind === "boolean") {
        body[field.name] = raw === true;
        continue;
      }
      const text = String(raw ?? "").trim();
      if (field.kind === "json") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(text);
        } catch {
          parsed = undefined;
        }
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setJsonError(t("payroll.ruleRow.invalidJson"));
          return;
        }
        body[field.name] = parsed;
      } else if (field.kind === "number" || field.kind === "money" || field.kind === "percent") {
        body[field.name] = text === "" ? null : Number(text);
      } else {
        body[field.name] = text === "" ? null : text;
      }
    }
    setJsonError(null);
    const request = row ? update.mutateAsync({ rowId: row.id, changes: body }) : add.mutateAsync(body);
    request
      .then(() => {
        toast.success(t("payroll.ruleRow.saved"));
        onOpenChange(false);
      })
      .catch((error: Error) => toast.error(t("payroll.rules.actionFailed"), { description: error.message }));
  };

  const control = (field: RuleRowField) => {
    const id = `rule-row-${field.name}`;
    const value = values[field.name];
    switch (field.kind) {
      case "select":
        return (
          <Select id={id} required={field.required} value={String(value ?? "")} onChange={(event) => setValue(field.name, event.target.value)}>
            <option value="">—</option>
            {field.options?.map((option) => (
              <option key={option} value={option}>
                {t(optionLabelKey(option))}
              </option>
            ))}
          </Select>
        );
      case "json":
        return (
          <>
            <textarea
              id={id}
              required={field.required}
              rows={6}
              spellCheck={false}
              value={String(value ?? "")}
              onChange={(event) => setValue(field.name, event.target.value)}
              aria-invalid={jsonError ? true : undefined}
              className={cn(
                "flex w-full rounded-md border border-border bg-background px-3 py-1.5 font-mono text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                jsonError && "border-destructive focus-visible:ring-destructive",
              )}
            />
            {jsonError && <p className="text-xs text-destructive">{jsonError}</p>}
          </>
        );
      case "number":
      case "money":
      case "percent":
        return (
          <Input
            id={id}
            type="number"
            required={field.required}
            step={field.kind === "money" ? "1" : "any"}
            min={field.kind === "percent" || field.kind === "money" ? "0" : undefined}
            max={field.kind === "percent" ? "100" : undefined}
            value={String(value ?? "")}
            onChange={(event) => setValue(field.name, event.target.value)}
          />
        );
      default:
        return <Input id={id} required={field.required} value={String(value ?? "")} onChange={(event) => setValue(field.name, event.target.value)} />;
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={fields.length > 5 ? "max-w-2xl" : undefined}>
        <DialogHeader>
          <DialogTitle>{t(kindLabelKey(kind))}</DialogTitle>
          <DialogDescription>{row ? t("common.edit") : t("payroll.rules.rows.add")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {fields.map((field) =>
              field.kind === "boolean" ? (
                <div key={field.name} className="flex items-center gap-2 self-end pb-2">
                  <Checkbox
                    id={`rule-row-${field.name}`}
                    checked={values[field.name] === true}
                    onCheckedChange={(checked) => setValue(field.name, checked === true)}
                  />
                  <Label htmlFor={`rule-row-${field.name}`}>{t(field.labelKey)}</Label>
                </div>
              ) : (
                <div key={field.name} className={field.kind === "json" ? "sm:col-span-2" : undefined}>
                  <FormField id={`rule-row-${field.name}`} label={t(field.labelKey)} hint={field.hintKey ? t(field.hintKey) : undefined}>
                    {control(field)}
                  </FormField>
                </div>
              ),
            )}
          </div>
          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
