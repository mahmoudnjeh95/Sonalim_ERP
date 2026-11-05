import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { getSettings, listAlertRules, putAlertRule, putSetting } from "./api";

export function TreasurySettingsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canEdit = hasPermission("treasury.admin_config");
  const canSwitchPosting = hasPermission("treasury.admin_ledger_posting");

  const { data: settings } = useQuery({ queryKey: ["treasury", "settings"], queryFn: () => getSettings(token) });
  const { data: rulesData } = useQuery({ queryKey: ["treasury", "alert-rules"], queryFn: () => listAlertRules(token) });
  const rules = rulesData ?? [];
  const [limit, setLimit] = useState("");
  const [cutoff, setCutoff] = useState("");
  const [offsets, setOffsets] = useState<Record<string, string>>({});

  useEffect(() => {
    if (settings) {
      setLimit(settings.cash_payment_limit === null ? "" : String(settings.cash_payment_limit));
      setCutoff(settings.prior_year_invoice_cutoff ?? "");
    }
  }, [settings]);
  useEffect(() => {
    if (!rulesData) return;
    // Keyed on the query result, not on `rules`: its `?? []` fallback is a new array each render.
    setOffsets(Object.fromEntries(rulesData.map((r) => [`${r.direction}:${r.method}`, String(r.offset_days)])));
  }, [rulesData]);

  const fail = (error: unknown) =>
    toast.error(t("treasury.settings.saveError"), { description: error instanceof ApiError ? error.message : undefined });

  const limitMutation = useMutation({
    mutationFn: () => putSetting(token, "cash_payment_limit", limit === "" ? null : Number(limit)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "settings"] });
      toast.success(t("treasury.settings.saved"));
    },
    onError: fail,
  });
  const settingMutation = useMutation({
    mutationFn: ({ key, value }: { key: "receipts_collect_on_slip" | "ledger_posting_enabled" | "prior_year_invoice_cutoff"; value: unknown }) => putSetting(token, key, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "settings"] });
      toast.success(t("treasury.settings.saved"));
    },
    onError: fail,
  });
  const ruleMutation = useMutation({
    mutationFn: ({ direction, method }: { direction: string; method: string }) =>
      putAlertRule(token, direction, method, Number(offsets[`${direction}:${method}`])),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "alert-rules"] });
      toast.success(t("treasury.settings.saved"));
    },
    onError: fail,
  });

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.settings.cashLimit.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t("treasury.settings.cashLimit.help")}</p>
          <div className="space-y-1.5">
            <Label htmlFor="cash_limit">{t("treasury.settings.cashLimit.label")}</Label>
            <Input id="cash_limit" type="number" min="0" step="1" value={limit} disabled={!canEdit} onChange={(e) => setLimit(e.target.value)} />
          </div>
          {canEdit && (
            <Button onClick={() => limitMutation.mutate()} disabled={limitMutation.isPending}>
              {t("common.save")}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.settings.flow.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{t("treasury.settings.onSlip.label")}</p>
              <p className="text-sm text-muted-foreground">{t("treasury.settings.onSlip.help")}</p>
            </div>
            <Switch
              aria-label={t("treasury.settings.onSlip.label")}
              checked={settings?.receipts_collect_on_slip ?? true}
              disabled={!canEdit || settingMutation.isPending}
              onCheckedChange={(value: boolean) => settingMutation.mutate({ key: "receipts_collect_on_slip", value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="prior_cutoff">{t("treasury.settings.cutoff.label")}</Label>
            <p className="text-sm text-muted-foreground">{t("treasury.settings.cutoff.help")}</p>
            <div className="flex gap-2">
              <Input id="prior_cutoff" placeholder="03-16" value={cutoff} disabled={!canEdit} onChange={(e) => setCutoff(e.target.value)} />
              {canEdit && (
                <Button variant="outline" disabled={settingMutation.isPending} onClick={() => settingMutation.mutate({ key: "prior_year_invoice_cutoff", value: cutoff.trim() || null })}>
                  {t("common.save")}
                </Button>
              )}
            </div>
          </div>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{t("treasury.settings.ledger.label")}</p>
              <p className="text-sm text-muted-foreground">{t("treasury.settings.ledger.help")}</p>
            </div>
            <Switch
              aria-label={t("treasury.settings.ledger.label")}
              checked={settings?.ledger_posting_enabled ?? false}
              disabled={!canSwitchPosting || settingMutation.isPending}
              onCheckedChange={(value: boolean) => settingMutation.mutate({ key: "ledger_posting_enabled", value })}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.settings.alerts.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t("treasury.settings.alerts.help")}</p>
          {rules.map((rule) => {
            const key = `${rule.direction}:${rule.method}`;
            return (
              <div key={key} className="flex items-end gap-3">
                <div className="flex-1 space-y-1.5">
                  <Label htmlFor={`rule_${key}`}>{t(`treasury.alert.${rule.direction}.${rule.method}`)}</Label>
                  <Input id={`rule_${key}`} type="number" step="1" value={offsets[key] ?? ""} disabled={!canEdit} onChange={(e) => setOffsets((o) => ({ ...o, [key]: e.target.value }))} />
                </div>
                {canEdit && (
                  <Button variant="outline" onClick={() => ruleMutation.mutate({ direction: rule.direction, method: rule.method })}>
                    {t("common.save")}
                  </Button>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
