import { useQuery } from "@tanstack/react-query";
import type { UseFormRegisterReturn } from "react-hook-form";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Label } from "../ui/label";
import { Select } from "../ui/select";
import {
  REPORT_OPTIONS_QUERY_KEY,
  listReportOptions,
  optionsFor,
} from "../../lib/reportOptions";

/**
 * The team and shift a report is filed under.
 *
 * Every report type asks the same two questions, and until these lists existed
 * each asked them as free text — so "Matin", "matin" and "MATIN" were three
 * different shifts and none of them grouped. The lists are configured in
 * production settings; an empty list still lets the field be left blank rather
 * than blocking the form, because a plant that has not set its shifts up yet
 * must still be able to file today's report.
 */
export function ShiftTeamFields({
  idPrefix,
  teamField,
  shiftField,
  currentTeam,
  currentShift,
}: {
  /** Keeps ids unique when two report forms are mounted at once. */
  idPrefix: string;
  teamField: UseFormRegisterReturn;
  shiftField: UseFormRegisterReturn;
  /** What the report already says, so a retired name is never silently dropped. */
  currentTeam?: string | null;
  currentShift?: string | null;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data: options = [] } = useQuery({
    queryKey: REPORT_OPTIONS_QUERY_KEY,
    queryFn: () => listReportOptions(session!.token),
  });

  const teams = optionsFor(options, "team", currentTeam);
  const shifts = optionsFor(options, "shift", currentShift);

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}team`}>{t("production.reports.field.team")}</Label>
        <Select id={`${idPrefix}team`} {...teamField}>
          <option value="">—</option>
          {teams.map((label) => (
            <option key={label} value={label}>
              {label}
            </option>
          ))}
        </Select>
        {teams.length === 0 && (
          <p className="text-xs text-muted-foreground">{t("production.reportOptions.emptyHint")}</p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}shift`}>{t("production.reports.field.shift")}</Label>
        <Select id={`${idPrefix}shift`} {...shiftField}>
          <option value="">—</option>
          {shifts.map((label) => (
            <option key={label} value={label}>
              {label}
            </option>
          ))}
        </Select>
        {shifts.length === 0 && (
          <p className="text-xs text-muted-foreground">{t("production.reportOptions.emptyHint")}</p>
        )}
      </div>
    </>
  );
}
