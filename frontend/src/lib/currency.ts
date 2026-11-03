import { currentLocale } from "./i18n";

/** The code the app prints after every amount.
 *
 * Deliberately NOT `Intl`'s `style: "currency"`: ICU's symbol for XOF is
 * "F CFA", so a currency-styled format silently disagrees with the "XOF" the
 * rest of the app prints, and the same figure reads two ways on one screen
 * (a stat card against the table below it). The number is grouped by locale;
 * the code is appended verbatim.
 */
export const CURRENCY_CODE = "XOF";

/** An XOF amount, grouped and with no decimals -- the currency has
 * none. Shared so the stock table, its overview, its analysis tab and its
 * valuation tab all print the same figure the same way. */
export function formatXof(amount: number): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

/** An XOF amount with its code: "104 528 500 XOF". */
export function formatXofWithCode(amount: number): string {
  return `${formatXof(amount)} ${CURRENCY_CODE}`;
}
