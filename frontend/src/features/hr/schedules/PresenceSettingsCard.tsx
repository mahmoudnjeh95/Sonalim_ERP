import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { HR_KEYS, getPresenceSettings, savePresenceSettings, type PresenceSettings, type PresenceSettingsValues } from "../presenceApi";
import { clockToMinutes, errorText, formatDay, minutesToClock } from "../presenceFormat";

interface SettingsDraft { nightStart: string; nightEnd: string; attach: string; dedupe: string; grace: string; confirm: boolean }

function toDraft(settings: PresenceSettings): SettingsDraft {
  const text = (value: number | null) => (value === null ? "" : String(value));
  return {
    nightStart: minutesToClock(settings.night_start_minute), nightEnd: minutesToClock(settings.night_end_minute),
    attach: text(settings.punch_attach_minutes), dedupe: text(settings.punch_dedupe_seconds), grace: text(settings.late_grace_minutes),
    confirm: false,
  };
}

/** "" -> null; a whole number >= 0 -> that number; anything else -> undefined (invalid). */
function wholeOrEmpty(value: string): number | null | undefined {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 ? number : undefined;
}

export function PresenceSettingsCard() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: HR_KEYS.settings, queryFn: () => getPresenceSettings(token) });
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  useEffect(() => {
    if (settings.data) setDraft(toDraft(settings.data));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (values: PresenceSettingsValues & { confirm: boolean }) => savePresenceSettings(token, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.settings });
      toast.success(t("hr.presenceSettings.saved"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });

  function submit() {
    if (!draft) return;
    const nightStart = draft.nightStart ? clockToMinutes(draft.nightStart) : null;
    const nightEnd = draft.nightEnd ? clockToMinutes(draft.nightEnd) : null;
    const attach = wholeOrEmpty(draft.attach);
    const dedupe = wholeOrEmpty(draft.dedupe);
    const grace = wholeOrEmpty(draft.grace);
    if (attach === undefined || dedupe === undefined || grace === undefined || (draft.nightStart && nightStart === null) || (draft.nightEnd && nightEnd === null)) {
      setFormError(t("hr.presenceSettings.error.number"));
      return;
    }
    setFormError(null);
    save.mutate({
      night_start_minute: nightStart, night_end_minute: nightEnd, punch_attach_minutes: attach,
      punch_dedupe_seconds: dedupe, late_grace_minutes: grace, confirm: draft.confirm,
    });
  }

  if (!draft || !settings.data) return <Skeleton className="h-64 w-full" />;
  const field = (id: string, label: string, input: JSX.Element) => (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {input}
    </div>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.presenceSettings.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("hr.presenceSettings.help")}</p>
        {settings.data.confirmed && settings.data.confirmed_at ? (
          <Badge variant="success">{t("hr.presenceSettings.confirmedOn")} {formatDay(settings.data.confirmed_at.slice(0, 10))}</Badge>
        ) : (
          <Badge variant="warning">{t("hr.presenceSettings.notConfirmed")}</Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {field("night-start", t("hr.presenceSettings.nightStart"), <Input id="night-start" type="time" disabled={!canEdit} value={draft.nightStart} onChange={(e) => setDraft({ ...draft, nightStart: e.target.value })} />)}
          {field("night-end", t("hr.presenceSettings.nightEnd"), <Input id="night-end" type="time" disabled={!canEdit} value={draft.nightEnd} onChange={(e) => setDraft({ ...draft, nightEnd: e.target.value })} />)}
          {field("punch-attach", t("hr.presenceSettings.attach"), <Input id="punch-attach" type="number" min={0} disabled={!canEdit} value={draft.attach} onChange={(e) => setDraft({ ...draft, attach: e.target.value })} />)}
          {field("punch-dedupe", t("hr.presenceSettings.dedupe"), <Input id="punch-dedupe" type="number" min={0} disabled={!canEdit} value={draft.dedupe} onChange={(e) => setDraft({ ...draft, dedupe: e.target.value })} />)}
          {field("late-grace", t("hr.presenceSettings.grace"), <Input id="late-grace" type="number" min={0} disabled={!canEdit} value={draft.grace} onChange={(e) => setDraft({ ...draft, grace: e.target.value })} />)}
        </div>
        {canEdit && (
          <>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={draft.confirm} onCheckedChange={(value) => setDraft({ ...draft, confirm: value === true })} />
              {t("hr.presenceSettings.confirm")}
            </label>
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
