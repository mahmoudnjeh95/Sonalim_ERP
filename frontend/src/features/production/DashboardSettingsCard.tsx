import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutDashboard } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { REPORT_OPTIONS_QUERY_KEY, listReportOptions } from "../../lib/reportOptions";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { listLocations } from "../warehouse/api";
import {
  DASHBOARD_SETTINGS_QUERY_KEY,
  MANAGE_DASHBOARD_SETTINGS_PERMISSION,
  getDashboardSettings,
  replaceShiftWindows,
  replaceStoreRoles,
  replaceTeamRotation,
  type DashboardSettings,
  type StoreRole,
} from "./board/api";
import { AppLoader } from "../../components/patterns/AppLoader";

function useSaveSection<T>(save: (token: string, items: T[]) => Promise<unknown>) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: T[]) => save(session!.token, items),
    onSuccess: () => {
      toast.success(t("production.board.settings.saved"));
      void queryClient.invalidateQueries({ queryKey: DASHBOARD_SETTINGS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: ["production", "board"] });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : String(error)),
  });
}

function Section({ title, hint, canEdit, saving, onSave, children }: { title: string; hint?: string; canEdit: boolean; saving: boolean; onSave: () => void; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <section className="space-y-3 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-primary">{title}</h3>
          {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        {canEdit ? (
          <Button size="sm" onClick={onSave} disabled={saving}>
            {t("production.board.settings.save")}
          </Button>
        ) : null}
      </div>
      {children}
    </section>
  );
}

// --- Shift hours ------------------------------------------------------------

function ShiftHoursForm({ shifts, initial, canEdit }: { shifts: string[]; initial: DashboardSettings["shift_windows"]; canEdit: boolean }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<Record<string, { start: string; end: string }>>(() =>
    Object.fromEntries(initial.map((w) => [w.shift, { start: w.start_time, end: w.end_time }])),
  );
  const save = useSaveSection(replaceShiftWindows);

  return (
    <Section
      title={t("production.board.settings.shiftHours")}
      hint={t("production.board.settings.shiftHours.hint")}
      canEdit={canEdit && shifts.length > 0}
      saving={save.isPending}
      onSave={() =>
        save.mutate(
          shifts
            .filter((shift) => draft[shift]?.start && draft[shift]?.end)
            .map((shift) => ({ shift, start_time: draft[shift].start, end_time: draft[shift].end })),
        )
      }
    >
      {shifts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("production.board.settings.noShifts")}</p>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {shifts.map((shift) => (
            <div key={shift} className="rounded-lg border border-border p-3">
              <p className="mb-2 text-sm font-medium">{shift}</p>
              <div className="flex items-center gap-2">
                <label className="flex-1 text-xs text-muted-foreground">
                  {t("production.board.settings.starts")}
                  <Input type="time" disabled={!canEdit} value={draft[shift]?.start ?? ""} onChange={(e) => setDraft({ ...draft, [shift]: { start: e.target.value, end: draft[shift]?.end ?? "" } })} />
                </label>
                <label className="flex-1 text-xs text-muted-foreground">
                  {t("production.board.settings.ends")}
                  <Input type="time" disabled={!canEdit} value={draft[shift]?.end ?? ""} onChange={(e) => setDraft({ ...draft, [shift]: { start: draft[shift]?.start ?? "", end: e.target.value } })} />
                </label>
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// --- Team rotation -----------------------------------------------------------

/**
 * The 4-team rotation: on a reference date, which team is on which shift.
 * The team left over from that date's picks is resting, computed, not chosen.
 */
function TeamRotationForm({ shifts, teams, initial, canEdit }: { shifts: string[]; teams: string[]; initial: DashboardSettings["team_rotation"]; canEdit: boolean }) {
  const { t } = useI18n();
  const [referenceDate, setReferenceDate] = useState(() => initial[0]?.anchor_date ?? new Date().toISOString().slice(0, 10));
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const teamByStop = Object.fromEntries(initial.map((r) => [r.anchor_stop, r.team]));
    return Object.fromEntries(shifts.map((shift, index) => [shift, teamByStop[index] ?? ""]));
  });
  const save = useSaveSection(replaceTeamRotation);

  const chosen = shifts.map((shift) => draft[shift]).filter(Boolean);
  const resting = teams.find((team) => !chosen.includes(team));
  const canSave = teams.length === shifts.length + 1 && chosen.length === shifts.length && new Set(chosen).size === chosen.length && resting !== undefined;

  return (
    <Section
      title={t("production.board.settings.teamRotation")}
      hint={t("production.board.settings.teamRotation.hint")}
      canEdit={canEdit && canSave}
      saving={save.isPending}
      onSave={() =>
        save.mutate([
          ...shifts.map((shift, index) => ({ team: draft[shift], anchor_date: referenceDate, anchor_stop: index })),
          { team: resting as string, anchor_date: referenceDate, anchor_stop: shifts.length },
        ])
      }
    >
      {shifts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("production.board.settings.noShifts")}</p>
      ) : teams.length !== shifts.length + 1 ? (
        <p className="text-sm text-muted-foreground">
          {t("production.board.settings.teamRotation.wrongCount")} ({shifts.length + 1})
        </p>
      ) : (
        <div className="space-y-3">
          <label className="block text-xs text-muted-foreground">
            {t("production.board.settings.teamRotation.referenceDate")}
            <Input type="date" disabled={!canEdit} value={referenceDate} onChange={(e) => setReferenceDate(e.target.value)} className="mt-1 w-40" />
          </label>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {shifts.map((shift) => (
              <div key={shift} className="rounded-lg border border-border p-3">
                <p className="mb-2 text-sm font-medium">{shift}</p>
                <Select disabled={!canEdit} value={draft[shift] ?? ""} onChange={(e) => setDraft({ ...draft, [shift]: e.target.value })}>
                  <option value="">{t("production.board.settings.noTeam")}</option>
                  {teams.map((team) => (
                    <option key={team} value={team}>{team}</option>
                  ))}
                </Select>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {resting
              ? `${t("production.board.settings.teamRotation.resting")}: ${resting}`
              : t("production.board.settings.teamRotation.incomplete")}
          </p>
        </div>
      )}
    </Section>
  );
}

// --- Machine stages and store roles -----------------------------------------

function AssignForm<V extends string>({
  title,
  rows,
  choices,
  initial,
  canEdit,
  emptyText,
  onSave,
  saving,
  noneLabel,
  choiceLabel,
}: {
  title: string;
  rows: { id: string; label: string; sub?: string }[];
  choices: readonly V[];
  initial: Record<string, V>;
  canEdit: boolean;
  emptyText: string;
  onSave: (picked: { id: string; value: V }[]) => void;
  saving: boolean;
  noneLabel: string;
  choiceLabel: (value: V) => string;
}) {
  const [draft, setDraft] = useState<Record<string, V | "">>(initial);
  return (
    <Section title={title} canEdit={canEdit && rows.length > 0} saving={saving} onSave={() => onSave(rows.filter((r) => draft[r.id]).map((r) => ({ id: r.id, value: draft[r.id] as V })))}>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.label}</p>
                {row.sub ? <p className="truncate text-xs text-muted-foreground">{row.sub}</p> : null}
              </div>
              <div className="w-44 shrink-0">
                <Select disabled={!canEdit} value={draft[row.id] ?? ""} onChange={(e) => setDraft({ ...draft, [row.id]: e.target.value as V | "" })}>
                  <option value="">{noneLabel}</option>
                  {choices.map((choice) => (
                    <option key={choice} value={choice}>{choiceLabel(choice)}</option>
                  ))}
                </Select>
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// --- The card ---------------------------------------------------------------

/**
 * What the production dashboard is configured with. All of it starts empty:
 * nothing is pre-filled with a suggested value, and the dashboard says "not
 * set" rather than guessing until someone fills it in.
 */
export function DashboardSettingsCard() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const canEdit = hasPermission(MANAGE_DASHBOARD_SETTINGS_PERMISSION);

  const settings = useQuery({ queryKey: DASHBOARD_SETTINGS_QUERY_KEY, queryFn: () => getDashboardSettings(token) });
  const options = useQuery({ queryKey: [...REPORT_OPTIONS_QUERY_KEY, "all"], queryFn: () => listReportOptions(token, true) });
  const locations = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const storeSave = useSaveSection(replaceStoreRoles);

  const ready = settings.data && options.data && locations.data;
  const activeOf = (kind: "shift" | "team") => (options.data ?? []).filter((o) => o.kind === kind && o.is_active).map((o) => o.label);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
          {t("production.board.settings.title")}
        </CardTitle>
        <CardDescription>{t("production.board.settings.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!ready ? (
          <AppLoader size={96} className="py-4" />
        ) : (
          <>
            <ShiftHoursForm key={`h-${JSON.stringify(settings.data!.shift_windows)}`} shifts={activeOf("shift")} initial={settings.data!.shift_windows} canEdit={canEdit} />
            <TeamRotationForm
              key={`tr-${JSON.stringify(settings.data!.team_rotation)}-${JSON.stringify(settings.data!.shift_order)}`}
              shifts={settings.data!.shift_order}
              teams={activeOf("team")}
              initial={settings.data!.team_rotation}
              canEdit={canEdit}
            />
            <AssignForm<StoreRole>
              key={`t-${JSON.stringify(settings.data!.store_roles)}`}
              title={t("production.board.settings.stores")}
              rows={locations.data!.map((l) => ({ id: l.id, label: l.name, sub: l.code }))}
              choices={["line", "final"] as const}
              initial={Object.fromEntries(settings.data!.store_roles.map((s) => [s.location_id, s.role]))}
              canEdit={canEdit}
              emptyText={t("production.board.stock.empty")}
              saving={storeSave.isPending}
              onSave={(picked) => storeSave.mutate(picked.map((p) => ({ location_id: p.id, role: p.value })))}
              noneLabel={t("production.board.settings.role.none")}
              choiceLabel={(role) => t(`production.board.settings.role.${role}` as TranslationKey)}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
