import { useCallback, useSyncExternalStore } from "react";
import { currentLocale } from "./i18n";

/**
 * The unit a weight figure is *shown* in. Stored figures never change, and they
 * are not all in one unit — each is in its own product's unit of measure — so a
 * caller first restates a quantity in kg (via that unit's `ratio_to_base`) and
 * this module does the rest. Purely a view choice, and the one place that
 * converts to tonnes, so no screen re-derives `/ 1000` on its own.
 */
export type WeightUnit = "kg" | "t";

const STORAGE_KEY = "sonalim.weightUnit";
const CHANGE_EVENT = "sonalim:weight-unit-change";
const KG_PER_TONNE = 1000;
// Tonnes is the plant's reading unit; kilos stay one click away.
const DEFAULT_UNIT: WeightUnit = "t";

function readStoredUnit(): WeightUnit {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "kg" || stored === "t" ? stored : DEFAULT_UNIT;
  } catch {
    return DEFAULT_UNIT;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * The viewer's chosen weight unit, remembered across visits and shared by
 * every component that uses it, so flipping it once flips every weight view.
 */
export function useWeightUnit(): [WeightUnit, (unit: WeightUnit) => void] {
  const unit = useSyncExternalStore(subscribe, readStoredUnit, () => DEFAULT_UNIT);
  const setUnit = useCallback((next: WeightUnit) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // storage blocked — the choice just won't outlive this page
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [unit, setUnit];
}

/** A weight in kilograms, restated in the chosen unit. */
export function fromKg(kg: number, unit: WeightUnit): number {
  return unit === "t" ? kg / KG_PER_TONNE : kg;
}

/**
 * The unit that reads best for a weight of this size: kilos below one tonne
 * (0.11 t is 110 kg), tonnes from one tonne up. Unlike `useWeightUnit` this is
 * about the figure, not the viewer's preference, for screens that show a single
 * total rather than a table the viewer can flip.
 */
export function autoWeightUnit(kg: number): WeightUnit {
  return Math.abs(kg) < KG_PER_TONNE ? "kg" : "t";
}

/**
 * Fraction digits by unit. A tonne is a thousand kilos, so a 100 g écart is
 * 0.0001 t: too few digits would print it as a flat 0 and make a real loss
 * look like none.
 */
const MAX_FRACTION_DIGITS: Record<WeightUnit, number> = { kg: 2, t: 5 };

/** A weight in kilograms, formatted in the chosen unit, without the unit suffix. */
export function formatWeightKg(kg: number, unit: WeightUnit): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: MAX_FRACTION_DIGITS[unit] }).format(fromKg(kg, unit));
}
