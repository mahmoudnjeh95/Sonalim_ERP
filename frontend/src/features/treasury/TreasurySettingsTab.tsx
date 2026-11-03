import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { getSettings, listAlertRules, putAlertRule, putSetting } from "./api";

export function TreasurySettingsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canEdit = hasPermission("treasury.admin_config");

  const { data: settings } = useQuery({ queryKey: ["treasury", "settings"], queryFn: () => getSettings(token) });
  const { data: rules = [] } = useQuery({ queryKey: ["treasury", "alert-rules"], queryFn: () => listAlertRules(token) });
  const [limit, setLimit] = useState("");
  const [offsets, setOffsets] = useState<Record<string, string>>({});

  useEffect(() => {
    if (settings) setLimit(settings.cash_payment_limit === null ? "" : String(settings.cash_payment_limit));
  }, [settings]);
  useEffect(() => {
    setOffsets(Object.fromEntries(rules.map((r) => [`${r.direction}:${r.method}`, String(r.offset_days)])));
  }, [rules]);

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
            <Input id="cash_limit" type="number" min="0" step="any" value={limit} disabled={!canEdit} onChange={(e) => setLimit(e.target.value)} />
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
