import { useState } from "react";
import { motion } from "framer-motion";
import { UserRound } from "lucide-react";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import RejectSvg from "../../../assets/icons/production/reject.svg?react";
import { downtimeLabel } from "../downtimeOptions";
import { useWasteTypes } from "../wasteTypes";
import type { BoardDay, BoardLine } from "./api";
import { formatNumber, shiftColor } from "./boardFormat";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const RejectIcon = outlineIcon(RejectSvg);

type Dimension = "primary" | "team" | "line";

interface Row {
  primary: string;
  team: string | null;
  line: string | null;
  value: number;
}

const LINE_COLOR = "#2F6FA8";

/**
 * One ranking of where something came from -- a stage or motif, a team, a
 * line -- cut from the same rows. Bars in the stage/motif view are split by
 * team, so "where" and "who" read together.
 */
function Ranking({
  title,
  icon,
  rows,
  primaryKey,
  primaryLabel,
  formatValue,
  emptyText,
}: {
  title: string;
  icon: React.ReactNode;
  rows: Row[];
  primaryKey: "rank.stage" | "rank.motif";
  primaryLabel: (key: string) => string;
  formatValue: (n: number) => string;
  emptyText: string;
}) {
  const { t } = useI18n();
  const [dimension, setDimension] = useState<Dimension>("primary");

  const teams = [...new Set(rows.map((r) => r.team).filter((x): x is string => x !== null))].sort();
  const colorOf = (team: string | null) => (team === null ? "#9db2c3" : shiftColor(teams.indexOf(team)));

  const groups = new Map<string, { key: string; label: string; total: number; segments: Map<string | null, number> }>();
  for (const row of rows) {
    const key = dimension === "primary" ? row.primary : dimension === "team" ? (row.team ?? "") : (row.line ?? "");
    const label = dimension === "primary" ? primaryLabel(row.primary) : dimension === "team" ? (row.team ?? t("production.board.rank.noTeam")) : (row.line ?? "—");
    const group = groups.get(key) ?? { key, label, total: 0, segments: new Map<string | null, number>() };
    group.total += row.value;
    const segmentKey = dimension === "primary" ? row.team : null;
    group.segments.set(segmentKey, (group.segments.get(segmentKey) ?? 0) + row.value);
    groups.set(key, group);
  }
  const ordered = [...groups.values()].sort((a, b) => b.total - a.total);
  const largest = ordered[0]?.total ?? 1;

  const dimensions: { id: Dimension; label: string }[] = [
    { id: "primary", label: t(`production.board.${primaryKey}` as TranslationKey) },
    { id: "team", label: t("production.board.rank.team") },
    { id: "line", label: t("production.board.rank.line") },
  ];

  return (
    <section className="rounded-xl border border-border bg-white p-4 shadow-soft">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-primary">
          {icon}
          {title}
        </h3>
        <div className="flex gap-1.5">
          {dimensions.map((d) => (
            <button key={d.id} type="button" onClick={() => setDimension(d.id)} className={cn("rounded-lg border px-2.5 py-1 text-xs transition-colors", dimension === d.id ? "border-primary bg-primary text-primary-foreground" : "border-border bg-white text-primary hover:bg-muted")}>
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {ordered.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <div className="space-y-2">
          {/* Rows are keyed by what they are, not by their name: two kinds can share a name for
              a moment (both "—" until the waste-type list loads), and a shared key leaves a
              stale row behind. */}
          {ordered.map((group) => (
            <div key={group.key} className="grid grid-cols-[9.5rem_1fr_4rem] items-center gap-2 text-sm">
              <span className="truncate" title={group.label}>{group.label}</span>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
                {[...group.segments.entries()].map(([team, value]) => (
                  <motion.span key={team ?? "none"} className="h-full" style={{ background: dimension === "line" ? LINE_COLOR : colorOf(team) }} initial={{ width: 0 }} animate={{ width: `${(value / largest) * 100}%` }} transition={{ duration: 0.8 }} />
                ))}
              </div>
              <b className="text-right tabular-nums">{formatValue(group.total)}</b>
            </div>
          ))}
        </div>
      )}

      {dimension === "primary" && teams.length > 0 ? (
        <p className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {t("production.board.rank.splitByTeam")}
          {teams.map((team, i) => (
            <span key={team} className="inline-flex items-center gap-1">
              <UserRound className="h-3.5 w-3.5" style={{ color: shiftColor(i) }} strokeWidth={2.6} aria-hidden="true" />
              {team}
            </span>
          ))}
        </p>
      ) : null}
    </section>
  );
}

export function RankingCards({ day, lines }: { day: BoardDay; lines: BoardLine[] | undefined }) {
  const { t } = useI18n();
  const { label: wasteLabel } = useWasteTypes();
  const lineName = (id: string | null) => (id === null ? null : (lines?.find((l) => l.work_center_id === id)?.name ?? id));

  const waste: Row[] = day.waste.map((w) => ({ primary: w.category, team: w.team, line: lineName(w.work_center_id), value: w.value }));
  const stops: Row[] = day.stops.map((s) => ({ primary: s.motif ?? "", team: s.team, line: lineName(s.work_center_id), value: s.value }));

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <Ranking
        title={t("production.board.rank.waste")}
        icon={<RejectIcon className="h-4 w-4" aria-hidden="true" />}
        rows={waste}
        primaryKey="rank.stage"
        primaryLabel={wasteLabel}
        formatValue={(n) => formatNumber(n, 0)}
        emptyText={t("production.board.rank.waste.empty")}
      />
      <Ranking
        title={t("production.board.rank.stops")}
        icon={<DowntimeIcon className="h-4 w-4" aria-hidden="true" />}
        rows={stops}
        primaryKey="rank.motif"
        primaryLabel={(key) => (key ? downtimeLabel(t, "motif", key) : "—")}
        formatValue={(n) => formatDuration(Math.round(n))}
        emptyText={t("production.board.rank.stops.empty")}
      />
    </div>
  );
}
