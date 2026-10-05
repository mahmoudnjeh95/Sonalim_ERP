import { useMemo } from "react";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { CURRENCY_CODE } from "../../../lib/currency";
import { downtimeLabel } from "../../production/downtimeOptions";
import type { WasteCategory } from "../../production/api";
import { useWasteTypes } from "../../production/wasteTypes";
import type { Formatters, InsightText } from "./insights";

/** Same `{placeholder}` convention the rest of the app uses with t(). */
export function fill(template: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce((text, [name, value]) => text.split(`{${name}}`).join(value), template);
}

export function formatNumber(value: number, digits = 0): string {
  return new Intl.NumberFormat(currentLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** Percent figure such as 94.8%, or an em dash when the input is missing. */
export function formatPercent(value: number | null, digits = 1): string {
  return value === null ? "—" : `${formatNumber(value, digits)}%`;
}

export function useInsightText() {
  const { t } = useI18n();
  return (text: InsightText) => fill(t(text.key), text.vars);
}

export function useFormatters(machineLabel: (equipmentId: string) => string): Formatters {
  const { t, language } = useI18n();
  const { label: wasteLabel } = useWasteTypes();
  return useMemo(
    () => ({
      number: formatNumber,
      tonnes: (value) => `${formatNumber(value, value < 10 ? 2 : 1)} t`,
      kg: (value) => `${formatNumber(value, value < 10 ? 1 : 0)} kg`,
      duration: formatDuration,
      money: (value) => `${formatNumber(value, 0)} ${CURRENCY_CODE}`,
      machine: machineLabel,
      stage: (stage: WasteCategory) => wasteLabel(stage),
      motif: (motif: string) => downtimeLabel(t, "motif", motif),
      classification: (value: string) => downtimeLabel(t, "classification", value),
      downtimeType: (value: string) => downtimeLabel(t, "type", value),
    }),
    // language is not read directly but changes what formatNumber/t return.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [machineLabel, t, language, wasteLabel],
  );
}
