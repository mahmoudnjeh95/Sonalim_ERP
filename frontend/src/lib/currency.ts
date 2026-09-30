import { currentLocale } from "./i18n";

/** An XOF amount, grouped and with no decimals -- the currency has
 * none. Shared so the stock table, its overview, its analysis tab and its
 * valuation tab all print the same figure the same way. */
export function formatXof(amount: number): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}
