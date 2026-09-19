import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n } from "../../lib/i18n";
import { AnalyticsEmptyState } from "./AnalyticsStates";
import { formatPercent } from "./manufacturing/format";
import type { Formatters } from "./manufacturing/insights";
import type { OperationsSummary, QualitySummary } from "./manufacturing/metrics";
import ShiftTeamIllustration from "../../assets/illustrations/shift-team.svg?react";

/** Team output side by side. Teams are compared as operating units, never ranked or scored. */
export function TeamComparisonPanel({
  ops,
  quality,
  qualityUnavailable,
  fmt,
}: {
  ops: OperationsSummary;
  quality: QualitySummary | null;
  /** True when quality could not be loaded, so the column says so instead of showing dashes for "no data". */
  qualityUnavailable: boolean;
  fmt: Formatters;
}) {
  const { t } = useI18n();
  const conformityByTeam = new Map((quality?.byTeam ?? []).map((team) => [team.team, team.conformityPct]));

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("analytics.teams.title")}</CardTitle>
          <CardDescription>{t("analytics.teams.subtitle")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {ops.byTeam.length === 0 ? (
          <AnalyticsEmptyState
            illustration={ShiftTeamIllustration}
            title={t("analytics.teams.empty.title")}
            description={t("analytics.teams.empty.description")}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("analytics.teams.column.team")}</TableHead>
                <TableHead className="text-right">{t("analytics.teams.column.produced")}</TableHead>
                <TableHead className="text-right">{t("analytics.teams.column.yield")}</TableHead>
                <TableHead className="text-right">{t("analytics.teams.column.downtime")}</TableHead>
                <TableHead className="text-right">{t("analytics.teams.column.conformity")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ops.byTeam.map((team) => (
                <TableRow key={team.team}>
                  <TableCell className="font-medium">{team.team}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt.tonnes(team.produced)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPercent(team.yieldPct)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPercent(team.downtimeRatePct)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {qualityUnavailable ? (
                      <span className="text-muted-foreground" title={t("analytics.teams.qualityUnavailable")}>
                        —
                      </span>
                    ) : (
                      formatPercent(conformityByTeam.get(team.team) ?? null)
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
