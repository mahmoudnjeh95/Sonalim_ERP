import { FilterTabs } from "../../components/patterns/FilterTabs";
import { currentLocale, useI18n } from "../../lib/i18n";
import { fill } from "./manufacturing/format";
import type { DateWindow } from "./manufacturing/metrics";

export const PERIOD_DAYS = [7, 30, 90, 365] as const;
export type PeriodDays = (typeof PERIOD_DAYS)[number];

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(new Date(`${iso}T00:00:00`));
}

export function formatWindow(window: DateWindow): string {
  return `${shortDate(window.from)} – ${shortDate(window.to)}`;
}

export function PeriodFilter({
  days,
  onChange,
  windows,
}: {
  days: PeriodDays;
  onChange: (days: PeriodDays) => void;
  windows: { current: DateWindow; previous: DateWindow };
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <FilterTabs
        options={PERIOD_DAYS.map((value) => ({
          value: String(value),
          label: value === 365 ? t("analytics.preset.12m") : fill(t("analytics.period.days"), { days: String(value) }),
        }))}
        value={String(days)}
        onChange={(value) => onChange(Number(value) as PeriodDays)}
      />
      <p className="text-xs text-muted-foreground">
        {fill(t("analytics.period.comparison"), { current: formatWindow(windows.current), previous: formatWindow(windows.previous) })}
      </p>
    </div>
  );
}
