import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import type { ShiftReport, ShiftStatus } from "./shift/shiftApi";

// Worst first: a slot that two lines shared shows the state that still needs someone.
const PRECEDENCE: ShiftStatus[] = ["returned", "open", "submitted", "validated"];

const TONE: Record<ShiftStatus, string> = {
  validated: "bg-success hover:ring-success/40",
  submitted: "bg-warning hover:ring-warning/40",
  open: "bg-primary/55 hover:ring-primary/40",
  returned: "bg-destructive hover:ring-destructive/40",
};

// The plant's day runs morning → afternoon → night; anything else keeps its own order after them.
const SHIFT_ORDER: Record<string, number> = {
  matin: 0,
  morning: 0,
  "après-midi": 1,
  "apres-midi": 1,
  afternoon: 1,
  nuit: 2,
  night: 2,
};

function daysBetween(first: string, last: string): string[] {
  const days: string[] = [];
  const cursor = new Date(`${first}T00:00:00Z`);
  const end = new Date(`${last}T00:00:00Z`);
  while (cursor <= end) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

/**
 * Every shift that worked on the order, one cell per day and shift. A cell opens
 * that shift's report; an empty cell is a slot nobody reported on this order.
 */
export function ShiftCalendar({
  shifts,
  lineName,
}: {
  shifts: ShiftReport[];
  lineName: (workCenterId: string) => string;
}) {
  const { t } = useI18n();
  if (shifts.length === 0) return null;

  const dates = shifts.map((s) => s.report_date).sort();
  const days = daysBetween(dates[0], dates[dates.length - 1]);
  const shiftNames = [...new Set(shifts.map((s) => s.shift))].sort(
    (a, b) => (SHIFT_ORDER[a.toLowerCase()] ?? 9) - (SHIFT_ORDER[b.toLowerCase()] ?? 9) || a.localeCompare(b),
  );
  const slot = new Map<string, ShiftReport[]>();
  for (const shift of shifts) {
    const key = `${shift.report_date}|${shift.shift}`;
    slot.set(key, [...(slot.get(key) ?? []), shift]);
  }
  const counts = PRECEDENCE.map((status) => ({ status, count: shifts.filter((s) => s.status === status).length }));

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto pb-1">
        <div
          className="grid w-max gap-[3px]"
          style={{ gridTemplateColumns: `4.5rem repeat(${days.length}, 1.1rem)` }}
        >
          <span />
          {days.map((day, index) => {
            const dayOfMonth = Number(day.slice(8, 10));
            const monthStart = index === 0 || dayOfMonth === 1;
            return (
              <span
                key={day}
                className={cn(
                  "text-center text-[10px] tabular-nums leading-4",
                  monthStart ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {index % 2 === 0 || monthStart ? dayOfMonth : ""}
              </span>
            );
          })}
          {shiftNames.map((name, row) => (
            <Row
              key={name}
              name={name}
              row={row}
              days={days}
              slot={slot}
              lineName={lineName}
              statusLabel={(status) => t(`status.${status}` as Parameters<typeof t>[0])}
            />
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        {counts.map(({ status, count }) => (
          <span key={status} className="inline-flex items-center gap-1.5">
            <span className={cn("h-2.5 w-2.5 rounded-[3px]", TONE[status].split(" ")[0])} />
            {t(`status.${status}` as Parameters<typeof t>[0])}
            <span className="font-medium tabular-nums text-foreground">{count}</span>
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[3px] bg-muted" />
          {t("production.ofDetails.calendar.noShift")}
        </span>
      </div>
    </div>
  );
}

function Row({
  name,
  row,
  days,
  slot,
  lineName,
  statusLabel,
}: {
  name: string;
  row: number;
  days: string[];
  slot: Map<string, ShiftReport[]>;
  lineName: (workCenterId: string) => string;
  statusLabel: (status: ShiftStatus) => string;
}) {
  return (
    <>
      <span className="truncate pr-1 text-xs capitalize leading-[1.1rem] text-muted-foreground" title={name}>
        {name}
      </span>
      {days.map((day, column) => {
        const reports = slot.get(`${day}|${name}`);
        if (!reports) return <span key={day} className="h-[1.1rem] rounded-[4px] bg-muted" />;
        const status = PRECEDENCE.find((s) => reports.some((r) => r.status === s)) ?? reports[0].status;
        const first = reports[0];
        const title = [
          `${day} · ${name}`,
          ...reports.map((r) => `${lineName(r.work_center_id)} — ${statusLabel(r.status)}`),
        ].join("\n");
        return (
          <motion.span
            key={day}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.18, delay: Math.min(0.6, (column + row * 3) * 0.008) }}
          >
            <Link
              to={`/production?tab=shift-report&line=${encodeURIComponent(first.work_center_id)}&date=${day}&shift=${encodeURIComponent(name)}`}
              title={title}
              aria-label={title}
              className={cn(
                "block h-[1.1rem] rounded-[4px] transition-shadow hover:ring-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                TONE[status],
              )}
            />
          </motion.span>
        );
      })}
    </>
  );
}
