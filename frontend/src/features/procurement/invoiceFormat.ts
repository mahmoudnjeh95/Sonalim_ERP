import { currentLocale } from "../../lib/i18n";

/** F CFA, whole francs. */
export function formatXof(value: string | number | null | undefined) {
  const amount = Number(value ?? 0);
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency: "XOF", maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${Math.round(amount)} F CFA`;
  }
}

/** A quantity or rate without trailing zeros: "18.00" shows as 18. */
export const plain = (value: string | number) => String(Number(value));
