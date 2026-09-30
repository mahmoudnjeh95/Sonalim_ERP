import { currentLocale } from "../../lib/i18n";

/** Whole XOF in the app's language ("150 000 XOF"); "—" when the value is hidden or absent. */
export function formatXof(amount: number | null | undefined): string {
  if (amount == null) return "—";
  return new Intl.NumberFormat(currentLocale(), { style: "currency", currency: "XOF", maximumFractionDigits: 0 }).format(amount);
}

/** An amount in whatever currency it is actually recorded in (a legacy non-XOF contract keeps
 * its own currency rather than being relabelled XOF); "—" when the value is hidden or absent. */
export function formatMoney(amount: number | null | undefined, currency: string): string {
  if (amount == null) return "—";
  if (currency === "XOF") return formatXof(amount);
  return new Intl.NumberFormat(currentLocale(), { style: "currency", currency }).format(amount);
}

/** An ISO date (yyyy-mm-dd) in the app's language; "—" when absent. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString(currentLocale());
}

/** Today as yyyy-mm-dd in the browser's time zone (toISOString would give UTC's date). */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** A form value for the API: trimmed, and blank means "no value". */
export function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}
