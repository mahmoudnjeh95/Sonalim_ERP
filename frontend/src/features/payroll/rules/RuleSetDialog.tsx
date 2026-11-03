import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { FormField } from "../../hr/FormField";
import {
  DAILY_REST_DAY_PAY_MODES,
  ROUND_MODES,
  useCreateRuleSet,
  usePayrollSettings,
  useUpdateRuleSet,
  type RuleSetDocument,
  type RuleSetHeader,
  type RuleSetInput,
} from "../api";
import { monthInputValue, parseMonthInput } from "../format";

interface FormState {
  country: string;
  name: string;
  validFrom: string;
  workingDays: string;
  workingHours: string;
  roundTo: string;
  roundMode: string;
  taxRoundTo: string;
  taxRoundMode: string;
  settlementMonths: string;
  dailyRestDayPay: string;
  notes: string;
}

const text = (value: number | string | null | undefined) => (value === null || value === undefined ? "" : String(value));

function initialForm(ruleSet: RuleSetHeader | undefined, country: string): FormState {
  // A new rule set starts empty (no suggested number); only the payroll country is carried over.
  return {
    country: ruleSet?.country ?? country,
    name: ruleSet?.name ?? "",
    validFrom: ruleSet ? monthInputValue(ruleSet.valid_from) : "",
    workingDays: text(ruleSet?.working_days_per_month),
    workingHours: text(ruleSet?.working_hours_per_month),
    roundTo: text(ruleSet?.round_to),
    roundMode: ruleSet?.round_mode ?? "",
    taxRoundTo: text(ruleSet?.tax_round_to),
    taxRoundMode: ruleSet?.tax_round_mode ?? "",
    settlementMonths: text(ruleSet?.settlement_reference_months),
    dailyRestDayPay: ruleSet?.daily_rest_day_pay ?? "",
    notes: ruleSet?.notes ?? "",
  };
}

/** Builds the request: an empty optional field is left out, so the server applies its own default. */
function toBody(form: FormState): RuleSetInput {
  const body: RuleSetInput = {
    country: form.country.trim().toUpperCase(),
    name: form.name.trim(),
    valid_from: parseMonthInput(form.validFrom),
    working_days_per_month: Number(form.workingDays),
    working_hours_per_month: Number(form.workingHours),
    notes: form.notes.trim() || null,
  };
  if (form.roundTo.trim()) body.round_to = Number(form.roundTo);
  if (form.roundMode) body.round_mode = form.roundMode as RuleSetInput["round_mode"];
  if (form.taxRoundTo.trim()) body.tax_round_to = Number(form.taxRoundTo);
  if (form.taxRoundMode) body.tax_round_mode = form.taxRoundMode as RuleSetInput["tax_round_mode"];
  if (form.settlementMonths.trim()) body.settlement_reference_months = Number(form.settlementMonths);
  if (form.dailyRestDayPay) body.daily_rest_day_pay = form.dailyRestDayPay as RuleSetInput["daily_rest_day_pay"];
  return body;
}

/** Create a rule set (no `ruleSet`) or edit a draft one's header. */
export function RuleSetDialog({
  open,
  onOpenChange,
  ruleSet,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ruleSet?: RuleSetHeader;
  onSaved?: (saved: RuleSetDocument) => void;
}) {
  const { t } = useI18n();
  const { data: settings } = usePayrollSettings();
  const create = useCreateRuleSet();
  const update = useUpdateRuleSet(ruleSet?.id ?? "");
  const [form, setForm] = useState<FormState>(() => initialForm(ruleSet, settings?.country ?? ""));
  const pending = create.isPending || update.isPending;

  useEffect(() => {
    if (open) setForm(initialForm(ruleSet, settings?.country ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ruleSet?.id]);

  const set = (key: keyof FormState) => (event: { target: { value: string } }) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = () => {
    const body = toBody(form);
    const request = ruleSet ? update.mutateAsync(body) : create.mutateAsync(body);
    request
      .then((saved) => {
        toast.success(t("payroll.rules.ruleSets.saved"));
        onSaved?.(saved);
        onOpenChange(false);
      })
      .catch((error: Error) => toast.error(t("payroll.rules.actionFailed"), { description: error.message }));
  };

  // Creating: an empty choice means "the engine's default". Editing: every value is already stored,
  // so the field must keep one (an omitted field would silently stay unchanged).
  const editing = !!ruleSet;
  const defaultOption = editing ? null : <option value="">{t("payroll.ruleSetForm.engineDefault")}</option>;

  const modeSelect = (id: string, key: "roundMode" | "taxRoundMode", labelKey: TranslationKey) => (
    <FormField id={id} label={t(labelKey)}>
      <Select id={id} required={editing} value={form[key]} onChange={set(key)}>
        {defaultOption}
        {ROUND_MODES.map((mode) => (
          <option key={mode} value={mode}>
            {t(`payroll.ruleSetForm.roundMode.${mode}` as TranslationKey)}
          </option>
        ))}
      </Select>
    </FormField>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{ruleSet ? t("payroll.rules.ruleSets.edit") : t("payroll.rules.ruleSets.new")}</DialogTitle>
          {!editing && <DialogDescription>{t("payroll.ruleSetForm.defaultsHint")}</DialogDescription>}
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <FormField id="rule-set-country" label={t("payroll.rules.settings.country")}>
              <Input id="rule-set-country" required maxLength={2} className="uppercase" value={form.country} onChange={set("country")} />
            </FormField>
            <div className="sm:col-span-2">
              <FormField id="rule-set-name" label={t("payroll.rules.ruleSets.name")}>
                <Input id="rule-set-name" required value={form.name} onChange={set("name")} />
              </FormField>
            </div>
            <FormField id="rule-set-valid-from" label={t("payroll.rules.ruleSets.validFrom")}>
              <Input id="rule-set-valid-from" type="month" required value={form.validFrom} onChange={set("validFrom")} />
            </FormField>
            <FormField id="rule-set-days" label={t("payroll.ruleSetForm.workingDays")}>
              <Input id="rule-set-days" type="number" required min="1" max="31" step="any" value={form.workingDays} onChange={set("workingDays")} />
            </FormField>
            <FormField id="rule-set-hours" label={t("payroll.ruleSetForm.workingHours")}>
              <Input id="rule-set-hours" type="number" required min="1" max="744" step="any" value={form.workingHours} onChange={set("workingHours")} />
            </FormField>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField id="rule-set-round-to" label={t("payroll.ruleSetForm.roundTo")}>
              <Input id="rule-set-round-to" type="number" required={editing} min="1" step="1" value={form.roundTo} onChange={set("roundTo")} />
            </FormField>
            {modeSelect("rule-set-round-mode", "roundMode", "payroll.ruleSetForm.roundMode")}
            <FormField id="rule-set-tax-round-to" label={t("payroll.ruleSetForm.taxRoundTo")}>
              <Input id="rule-set-tax-round-to" type="number" required={editing} min="1" step="1" value={form.taxRoundTo} onChange={set("taxRoundTo")} />
            </FormField>
            {modeSelect("rule-set-tax-round-mode", "taxRoundMode", "payroll.ruleSetForm.taxRoundMode")}
            <FormField id="rule-set-settlement" label={t("payroll.ruleSetForm.settlementReferenceMonths")}>
              <Input id="rule-set-settlement" type="number" required={editing} min="1" step="1" value={form.settlementMonths} onChange={set("settlementMonths")} />
            </FormField>
            <FormField id="rule-set-rest-day" label={t("payroll.ruleSetForm.dailyRestDayPay")}>
              <Select id="rule-set-rest-day" required={editing} value={form.dailyRestDayPay} onChange={set("dailyRestDayPay")}>
                {defaultOption}
                {DAILY_REST_DAY_PAY_MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {t(`payroll.ruleSetForm.dailyRestDayPay.${mode}` as TranslationKey)}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
          <FormField id="rule-set-notes" label={t("payroll.ruleSetForm.notes")}>
            <textarea
              id="rule-set-notes"
              rows={2}
              value={form.notes}
              onChange={set("notes")}
              className="flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </FormField>
          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
