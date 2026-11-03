import { useI18n } from "../../../lib/i18n";
import { Select } from "../../../components/ui/select";
import type { Department } from "../api";
import type { TeamFilter, WorkSchedule } from "../presenceApi";

export interface Team {
  kind: "department" | "schedule";
  id: string; // "" = everyone
}

export function teamFilterOf(team: Team): TeamFilter {
  if (!team.id) return {};
  return team.kind === "department" ? { departmentId: team.id } : { scheduleId: team.id };
}

/** A supervisor's team: one department, or everyone on one schedule that day. */
export function TeamPicker({ team, onChange, departments, schedules }: {
  team: Team;
  onChange: (team: Team) => void;
  departments: Department[];
  schedules: WorkSchedule[];
}) {
  const { t } = useI18n();
  const options = team.kind === "department"
    ? departments.map((d) => ({ id: d.id, label: `${d.code} · ${d.name}` }))
    : schedules.filter((s) => s.active).map((s) => ({ id: s.id, label: `${s.code} · ${s.name}` }));
  return (
    <div className="flex items-center gap-2">
      <Select aria-label={t("hr.presence.team")} value={team.kind} onChange={(e) => onChange({ kind: e.target.value as Team["kind"], id: "" })}>
        <option value="department">{t("hr.presence.teamKind.department")}</option>
        <option value="schedule">{t("hr.presence.teamKind.schedule")}</option>
      </Select>
      <Select aria-label={t("hr.presence.team")} value={team.id} onChange={(e) => onChange({ ...team, id: e.target.value })}>
        <option value="">{t("hr.presence.allTeams")}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </Select>
    </div>
  );
}
