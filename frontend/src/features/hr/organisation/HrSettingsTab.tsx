import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { getHrSettings, hrKeys, saveHrSettings, type HrSettings } from "../api";
import { FormField } from "../FormField";

const FIELDS: { key: keyof HrSettings; labelKey: TranslationKey }[] = [
  { key: "contract_expiry_horizon_days", labelKey: "hr.settings.contractDays" },
  { key: "trial_end_horizon_days", labelKey: "hr.settings.trialDays" },
  { key: "document_expiry_horizon_days", labelKey: "hr.settings.documentDays" },
];

export function HrSettingsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const canSave = hasPermission("hr.admin_employees");
  const { data, isLoading } = useQuery({ queryKey: hrKeys.settings, queryFn: () => getHrSettings(session!.token) });
  const [form, setForm] = useState<Record<keyof HrSettings, string>>({
    contract_expiry_horizon_days: "",
    trial_end_horizon_days: "",
    document_expiry_horizon_days: "",
  });

  useEffect(() => {
    if (!data) return;
    // Empty stays empty: an unset horizon is shown blank, never a suggested number.
    setForm({
      contract_expiry_horizon_days: data.contract_expiry_horizon_days == null ? "" : String(data.contract_expiry_horizon_days),
      trial_end_horizon_days: data.trial_end_horizon_days == null ? "" : String(data.trial_end_horizon_days),
      document_expiry_horizon_days: data.document_expiry_horizon_days == null ? "" : String(data.document_expiry_horizon_days),
    });
  }, [data]);

  const mutation = useMutation({
    mutationFn: () => {
      const value = (raw: string) => (raw.trim() === "" ? null : Number(raw));
      return saveHrSettings(session!.token, {
        contract_expiry_horizon_days: value(form.contract_expiry_horizon_days),
        trial_end_horizon_days: value(form.trial_end_horizon_days),
        document_expiry_horizon_days: value(form.document_expiry_horizon_days),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.settings });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      queryClient.invalidateQueries({ queryKey: ["hr", "employees"] });
      toast.success(t("hr.settings.saved"));
    },
    onError: (error) => toast.error(t("hr.settings.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  if (isLoading) return <AppLoader className="min-h-[200px]" size={120} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("hr.settings.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("hr.settings.description")}</p>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {FIELDS.map((field) => (
              <FormField key={field.key} id={field.key} label={t(field.labelKey)}>
                <Input
                  id={field.key}
                  type="number"
                  min="1"
                  step="1"
                  readOnly={!canSave}
                  value={form[field.key]}
                  onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
                />
              </FormField>
            ))}
          </div>
          {canSave ? (
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? t("common.saving") : t("common.save")}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">{t("hr.settings.readOnly")}</p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
