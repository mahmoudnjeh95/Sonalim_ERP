import { currentLocale } from "../../lib/i18n";

// Money is whole F CFA (XOF has no minor unit): integers in JSON, shown with the literal
// "F CFA" suffix rather than Intl's own "XOF" currency symbol.
export function formatXof(amount: number | null | undefined, locale: string = currentLocale()): string {
  if (amount === null || amount === undefined) return "—";
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(amount)} F CFA`;
}

// A payroll period is the first day of its month, "YYYY-MM-01".
export function periodParam(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-01`;
}

/** "YYYY-MM-01" -> "YYYY-MM", the value an `<input type="month">` takes. */
export function monthInputValue(period: string): string {
  return period.slice(0, 7);
}

/** "YYYY-MM" from an `<input type="month">` -> "YYYY-MM-01"; empty stays empty. */
export function parseMonthInput(value: string): string {
  return value ? `${value.slice(0, 7)}-01` : "";
}

/** "2031-09-01" -> "septembre 2031" / "September 2031". */
export function formatPeriod(period: string, locale: string = currentLocale()): string {
  const [year, month] = period.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(new Date(year, month - 1, 1));
}
