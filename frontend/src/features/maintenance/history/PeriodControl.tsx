import { useState } from "react";
import { DateRangeFilter } from "../../../components/patterns/DateRangeFilter";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { PERIOD_PRESETS, usePeriod, type PeriodPreset } from "./historyPeriod";

type Choice = PeriodPreset | "custom";

const LABEL: Record<Choice, TranslationKey> = {
  month: "maintenance.history.period.month",
  lastMonth: "maintenance.history.period.lastMonth",
  threeMonths: "maintenance.history.period.threeMonths",
  year: "maintenance.history.period.year",
  custom: "maintenance.history.period.custom",
};

/** Preset periods as chips, plus two dates for a custom one; the period itself lives in the URL. */
export function PeriodControl() {
  const { t } = useI18n();
  const { period, preset, isDefault, setPreset, setRange, reset } = usePeriod();
  const [customOpen, setCustomOpen] = useState(preset === null);
  const value: Choice = customOpen || preset === null ? "custom" : preset;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <FilterTabs<Choice>
        options={[...PERIOD_PRESETS, "custom" as const].map((choice) => ({ value: choice, label: t(LABEL[choice]) }))}
        value={value}
        onChange={(choice) => {
          if (choice === "custom") {
            setCustomOpen(true);
          } else {
            setCustomOpen(false);
            setPreset(choice);
          }
        }}
      />
      {value === "custom" && (
        <DateRangeFilter
          from={period.from}
          to={period.to}
          onChange={setRange}
          onReset={() => {
            setCustomOpen(false);
            reset();
          }}
          isDefault={isDefault}
        />
      )}
    </div>
  );
}
