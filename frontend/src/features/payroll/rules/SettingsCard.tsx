import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { FormField } from "../../hr/FormField";
import { usePayrollSettings, useSavePayrollSettings } from "../api";

/** The payroll country (picks the rule set in force) and the employer identifiers printed on payslips. */
export function SettingsCard() {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const canSave = hasPermission("payroll.manage_rules");
  const { data: settings, isSuccess } = usePayrollSettings();
  const save = useSavePayrollSettings();
  const [form, setForm] = useState({ country: "", address: "", inpsNo: "", taxId: "" });

  useEffect(() => {
    // Empty stays empty: nothing is suggested until the payroll country is first saved.
    setForm({
      country: settings?.country ?? "",
      address: settings?.company_address ?? "",
      inpsNo: settings?.employer_inps_no ?? "",
      taxId: settings?.employer_tax_id ?? "",
    });
  }, [settings]);

  const submit = () =>
    save.mutate(
      {
        country: form.country.trim().toUpperCase(),
        company_address: form.address.trim() || null,
        employer_inps_no: form.inpsNo.trim() || null,
        employer_tax_id: form.taxId.trim() || null,
      },
      {
        onSuccess: () => toast.success(t("payroll.rules.settings.saved")),
        onError: (error) => toast.error(t("payroll.rules.actionFailed"), { description: error.message }),
      },
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("payroll.rules.settings.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {isSuccess && settings === null && (
            <p className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm">{t("payroll.rules.settings.notSet")}</p>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <FormField id="payroll-country" label={t("payroll.rules.settings.country")}>
              <Input
                id="payroll-country"
                required
                maxLength={2}
                readOnly={!canSave}
                className="uppercase"
                value={form.country}
                onChange={(event) => setForm({ ...form, country: event.target.value.toUpperCase() })}
              />
            </FormField>
            <FormField id="payroll-inps" label={t("payroll.rules.settings.inpsNo")}>
              <Input id="payroll-inps" readOnly={!canSave} value={form.inpsNo} onChange={(event) => setForm({ ...form, inpsNo: event.target.value })} />
            </FormField>
            <FormField id="payroll-tax-id" label={t("payroll.rules.settings.taxId")}>
              <Input id="payroll-tax-id" readOnly={!canSave} value={form.taxId} onChange={(event) => setForm({ ...form, taxId: event.target.value })} />
            </FormField>
            <div className="sm:col-span-2 lg:col-span-4">
              <FormField id="payroll-address" label={t("payroll.rules.settings.address")}>
                <Input id="payroll-address" readOnly={!canSave} value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} />
              </FormField>
            </div>
          </div>
          {canSave ? (
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? t("common.saving") : t("payroll.rules.settings.save")}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">{t("payroll.rules.settings.readOnly")}</p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
