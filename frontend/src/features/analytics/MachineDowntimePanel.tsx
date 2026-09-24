import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { MotionSafeSvg } from "../../components/motion/MotionSafeSvg";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { DowntimeBreakdownRow, Machine } from "../production/api";
import { AnalyticsEmptyState } from "./AnalyticsStates";
import { formatPercent } from "./manufacturing/format";
import type { Formatters } from "./manufacturing/insights";
import { rankDowntimeReasons, type MachinesSummary } from "./manufacturing/metrics";
import AlertPulse from "../../assets/animations/alert-pulse.svg?react";
import MachineHealthPulse from "../../assets/animations/machine-health-pulse.svg?react";
import MachineMonitoring from "../../assets/illustrations/machine-monitoring.svg?react";

const MAX_ROWS = 5;

/** The machine's own recorded status (operational / down / maintenance), as icon + label — never colour alone. */
function MachineStatus({ status }: { status: Machine["status"] | null }) {
  const { t } = useI18n();
  if (!status) return null;
  const label = t(`analytics.machines.status.${status}` as TranslationKey);
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      {status === "operational" && (
        <MotionSafeSvg>
          <MachineHealthPulse aria-hidden viewBox="330 180 140 140" className="h-4 w-4" />
        </MotionSafeSvg>
      )}
      {status === "down" && (
        <MotionSafeSvg>
          <AlertPulse aria-hidden viewBox="340 190 120 120" className="h-4 w-4" />
        </MotionSafeSvg>
      )}
      {status === "maintenance" && <span aria-hidden className="mx-1 inline-block h-2 w-2 rounded-full bg-warning" />}
      {label}
    </span>
  );
}

export function MachineDowntimePanel({
  machines,
  breakdown,
  machineRecords,
  fmt,
}: {
  machines: MachinesSummary;
  breakdown: DowntimeBreakdownRow[];
  machineRecords: Machine[];
  fmt: Formatters;
}) {
  const { t } = useI18n();
  const rows = machines.machines.slice(0, MAX_ROWS);
  const worst = machines.machines[0];
  const reasons = worst ? rankDowntimeReasons(breakdown, worst.equipmentId).slice(0, 3) : [];
  const statusById = new Map(machineRecords.map((machine) => [machine.id, machine.status]));

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("analytics.machines.title")}</CardTitle>
          <CardDescription>{t("analytics.machines.subtitle")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {rows.length === 0 ? (
          <AnalyticsEmptyState
            illustration={MachineMonitoring}
            title={t("analytics.machines.empty.title")}
            description={t("analytics.machines.empty.description")}
          />
        ) : (
          <>
            <ul className="space-y-3">
              {rows.map((machine) => (
                <li key={machine.equipmentId} className="space-y-1.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                    <p className="text-sm font-medium">{fmt.machine(machine.equipmentId)}</p>
                    <MachineStatus status={statusById.get(machine.equipmentId) ?? null} />
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted" role="presentation">
                      <span
                        className="block h-full rounded-full bg-primary"
                        style={{ width: `${machine.shareOfDowntimePct ?? 0}%` }}
                      />
                    </span>
                    <span className="w-24 shrink-0 text-right text-sm tabular-nums">{fmt.duration(machine.downtimeMinutes)}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {t("analytics.machines.rate")} {formatPercent(machine.downtimeRatePct)} · {t("analytics.machines.share")}{" "}
                    {formatPercent(machine.shareOfDowntimePct, 0)}
                  </p>
                </li>
              ))}
            </ul>

            {reasons.length > 0 && worst && (
              <div className="border-t border-border pt-3">
                <p className="mb-2 text-xs font-medium text-muted-foreground">
                  {t("analytics.machines.reasons")} · {fmt.machine(worst.equipmentId)}
                </p>
                <ul className="flex flex-wrap gap-2">
                  {reasons.map((reason) => (
                    <li key={reason.reason} className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs">
                      {fmt.motif(reason.reason)} <span className="tabular-nums text-muted-foreground">· {fmt.duration(reason.minutes)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
