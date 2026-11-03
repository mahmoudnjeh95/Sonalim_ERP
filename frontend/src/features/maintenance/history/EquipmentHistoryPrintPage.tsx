import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import LogoMark from "../../../assets/animations/logo-mark.svg?react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { BrandWordmark } from "../../../components/patterns/BrandLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { PRINT_TABLE, PRINT_TD, PRINT_TH, PrintShell } from "../../../components/patterns/PrintShell";
import { useAuth } from "../../../lib/auth";
import { formatXofWithCode } from "../../../lib/currency";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { downtimeLabel } from "../../production/downtimeOptions";
import { formatDateTime, formatDay, formatMeasure } from "../jobs/jobFormat";
import { JOB_KIND_LABEL_KEY, OUTCOME_LABEL_KEY } from "../labels";
import { useEquipmentHistory, type TimelineItem } from "./api";
import { fill, minutesOrDash } from "./historyFormat";
import { usePeriod } from "./historyPeriod";

type Of<K extends TimelineItem["kind"]> = Extract<TimelineItem, { kind: K }>;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 break-inside-avoid">
      <h2 className="border-b border-[#F5A900] pb-1 text-sm font-semibold uppercase tracking-wide">{title}</h2>
      {children}
    </section>
  );
}

function Pairs({ rows }: { rows: [string, string][] }) {
  return (
    <table className={PRINT_TABLE}>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label}>
            <td className={PRINT_TD}>{label}</td>
            <td className={`${PRINT_TD} text-right font-semibold`}>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** /maintenance/equipment/:id/print — the machine's history on paper (browser print → PDF). */
export function EquipmentHistoryPrintPage() {
  const { equipmentId = "" } = useParams();
  const { session } = useAuth();
  const { t } = useI18n();
  const { period } = usePeriod();
  const history = useEquipmentHistory(session!.token, equipmentId, period);

  if (history.isLoading) return <AppLoader className="py-24" />;
  if (!history.data) {
    return (
      <EmptyState
        icon={<AlertTriangle className="h-5 w-5" />}
        title={t("maintenance.history.logbook.notFound")}
        description={t("maintenance.history.loadError")}
      />
    );
  }

  const data = history.data;
  const production = data.indicators.production;
  const maintenance = data.indicators.maintenance;
  const jobs = data.timeline.filter((item): item is Of<"job"> => item.kind === "job");
  const stops = data.timeline.filter((item): item is Of<"production_stop"> => item.kind === "production_stop");
  const changes = data.timeline.filter((item): item is Of<"status_change"> => item.kind === "status_change");
  const status = (value: string) => t(`maintenance.equipment.status.${value}` as TranslationKey);
  const none = <p className="text-xs text-neutral-500">{t("maintenance.history.print.none")}</p>;

  return (
    <PrintShell
      title={t("maintenance.history.print.title")}
      subtitle={
        <>
          {data.equipment.code} — {data.equipment.name}
          <br />
          {fill(t("maintenance.history.print.period"), { from: formatDay(period.from), to: formatDay(period.to) })}
        </>
      }
      company={null}
      brand={
        <div className="flex items-center gap-3 text-[#123B6D]">
          <LogoMark aria-hidden className="h-10 w-10" />
          <BrandWordmark tone="light" size={20} />
        </div>
      }
      backTo={`/maintenance/equipment/${equipmentId}?from=${period.from}&to=${period.to}`}
    >
      <div className="grid grid-cols-2 gap-6 print:grid-cols-2">
        <Section title={t("maintenance.history.production.title")}>
          {production ? (
            <Pairs
              rows={[
                [t("maintenance.history.kpi.breakdowns"), `${production.breakdowns} · ${formatDuration(production.breakdown_minutes)}`],
                [t("maintenance.history.kpi.mtbf"), minutesOrDash(production.mtbf_minutes)],
                [t("maintenance.history.kpi.mttr"), minutesOrDash(production.mttr_minutes)],
                [t("maintenance.history.kpi.allStops"), `${production.stops} · ${formatDuration(production.stop_minutes)}`],
              ]}
            />
          ) : (
            <p className="text-xs text-neutral-500">{t("maintenance.history.production.unavailable")}</p>
          )}
        </Section>
        <Section title={t("maintenance.history.maintenance.title")}>
          <Pairs
            rows={[
              [t("maintenance.history.kpi.breakdowns"), String(maintenance.breakdowns)],
              [t("maintenance.history.kpi.immobilisation"), formatDuration(maintenance.immobilised_minutes)],
              [t("maintenance.history.kpi.betweenBreakdowns"), minutesOrDash(maintenance.calendar_mtbf_minutes)],
              [
                t("maintenance.history.column.preventive"),
                maintenance.preventive.due === 0
                  ? "—"
                  : `${maintenance.preventive.closed}/${maintenance.preventive.due} · ${fill(t("maintenance.history.preventive.overdue"), {
                      n: maintenance.preventive.overdue,
                    })}`,
              ],
              [t("maintenance.history.kpi.technician"), formatDuration(maintenance.technician_seconds / 60)],
              ...(data.costs_visible && maintenance.parts_cost !== null
                ? ([[t("maintenance.history.kpi.partsCost"), formatXofWithCode(maintenance.parts_cost)]] as [string, string][])
                : []),
            ]}
          />
        </Section>
      </div>

      <Section title={t("maintenance.history.print.jobs")}>
        {jobs.length === 0 ? (
          none
        ) : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.number")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.date")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.kind")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.title")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.result")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.time")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(({ job }) => (
                <tr key={job.job_id}>
                  <td className={PRINT_TD}>{job.number}</td>
                  <td className={PRINT_TD}>{formatDay(job.date ?? job.created_at)}</td>
                  <td className={PRINT_TD}>{t(JOB_KIND_LABEL_KEY[job.kind])}</td>
                  <td className={PRINT_TD}>{job.title}</td>
                  <td className={PRINT_TD}>
                    {fill(t("maintenance.history.journal.result"), {
                      ok: job.outcomes.ok,
                      issue: job.outcomes.issue,
                      notDone: job.outcomes.not_done,
                    })}
                  </td>
                  <td className={PRINT_TD}>{formatDuration(job.technician_seconds / 60)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("maintenance.history.print.stops")}>
        {stops.length === 0 ? (
          none
        ) : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.date")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.duration")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.kind")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.system")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.reason")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.note")}</th>
              </tr>
            </thead>
            <tbody>
              {stops.map(({ stop }) => (
                <tr key={`${stop.shift_report_id}-${stop.started_at}`}>
                  <td className={PRINT_TD}>{formatDateTime(stop.started_at)}</td>
                  <td className={PRINT_TD}>{formatDuration(stop.minutes)}</td>
                  <td className={PRINT_TD}>{stop.downtime_type ? downtimeLabel(t, "type", stop.downtime_type) : "—"}</td>
                  <td className={PRINT_TD}>{stop.classification ? downtimeLabel(t, "classification", stop.classification) : "—"}</td>
                  <td className={PRINT_TD}>{stop.motif ? downtimeLabel(t, "motif", stop.motif) : "—"}</td>
                  <td className={PRINT_TD}>{stop.note ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("maintenance.history.print.statusChanges")}>
        {changes.length === 0 ? (
          none
        ) : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.journal.column.date")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.from")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.to")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.by")}</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((change) => (
                <tr key={`${change.at}-${change.to_status}`}>
                  <td className={PRINT_TD}>{formatDateTime(change.at)}</td>
                  <td className={PRINT_TD}>{status(change.from_status)}</td>
                  <td className={PRINT_TD}>{status(change.to_status)}</td>
                  <td className={PRINT_TD}>{change.actor_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("maintenance.history.print.points")}>
        {data.checkpoints.length === 0 ? (
          none
        ) : (
          <table className={PRINT_TABLE}>
            <thead>
              <tr>
                <th className={PRINT_TH}>{t("maintenance.history.points.title")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.point.checked")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.point.issues")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.point.last")}</th>
                <th className={PRINT_TH}>{t("maintenance.history.print.column.lastMeasure")}</th>
              </tr>
            </thead>
            <tbody>
              {data.checkpoints.map((point) => (
                <tr key={point.checkpoint_id}>
                  <td className={PRINT_TD}>{point.label}</td>
                  <td className={PRINT_TD}>{point.checks_count}</td>
                  <td className={PRINT_TD}>{point.issues_count}</td>
                  <td className={PRINT_TD}>
                    {point.last_checked_at && point.last_outcome
                      ? `${formatDay(point.last_checked_at)} · ${t(OUTCOME_LABEL_KEY[point.last_outcome])}`
                      : t("maintenance.history.points.never")}
                  </td>
                  <td className={PRINT_TD}>
                    {point.last_measured_value !== null ? formatMeasure(point.last_measured_value, point.measure_unit) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <p className="text-[10px] text-neutral-500">
        {fill(t("maintenance.history.print.printedOn"), { date: formatDateTime(new Date().toISOString()), user: session!.email })}
      </p>
    </PrintShell>
  );
}
