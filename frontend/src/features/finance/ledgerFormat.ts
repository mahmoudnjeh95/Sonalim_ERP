import { ApiError } from "../../lib/api";
import { currentLocale } from "../../lib/i18n";

/** Whole francs (XOF has no sub-unit), grouped the way the chosen language writes numbers. */
export function formatAmount(amount: number): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

/** An amount cell of a ledger table: blank for zero, the way accountants print books. */
export function formatAmountCell(amount: number): string {
  return amount === 0 ? "" : formatAmount(amount);
}

export function formatXof(amount: number): string {
  return `${formatAmount(amount)} F CFA`;
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "2-digit", month: "2-digit", year: "numeric" }).format(
    new Date(`${iso.slice(0, 10)}T00:00:00`),
  );
}

export function formatMonth(period: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric" }).format(new Date(`${period}T00:00:00`));
}

function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function todayIso(): string {
  return isoDay(new Date());
}

export function monthStartIso(date = new Date()): string {
  return isoDay(new Date(date.getFullYear(), date.getMonth(), 1));
}

export function monthEndIso(date = new Date()): string {
  return isoDay(new Date(date.getFullYear(), date.getMonth() + 1, 0));
}

export function yearStartIso(date = new Date()): string {
  return isoDay(new Date(date.getFullYear(), 0, 1));
}

export function errorText(error: unknown): string | undefined {
  return error instanceof ApiError ? error.message : undefined;
}
