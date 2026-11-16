/** The same totals the server computes (procurement.domain.purchase_invoice.compute_totals), for a live
 *  preview while lines are typed: exact per line, rounded half up to the franc on the totals. */
export interface LineAmounts {
  quantity: number;
  unit_price: number;
  discount_rate?: number;
  vat_rate?: number | null;
}

export interface Totals {
  gross: number;
  discount: number;
  excl: number;
  vat: number;
  incl: number;
}

const roundFranc = (value: number) => Math.round(value + Number.EPSILON);

export function lineNet(line: LineAmounts) {
  return (Number(line.quantity) || 0) * (Number(line.unit_price) || 0) * (100 - (Number(line.discount_rate) || 0)) / 100;
}

export function lineVat(line: LineAmounts, defaultVat: number) {
  const rate = line.vat_rate === null || line.vat_rate === undefined ? defaultVat : Number(line.vat_rate) || 0;
  return (lineNet(line) * rate) / 100;
}

export function computeTotals(lines: LineAmounts[], defaultVat: number): Totals {
  const gross = roundFranc(lines.reduce((sum, l) => sum + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0));
  const excl = roundFranc(lines.reduce((sum, l) => sum + lineNet(l), 0));
  const vat = roundFranc(lines.reduce((sum, l) => sum + lineVat(l, defaultVat), 0));
  return { gross, discount: gross - excl, excl, vat, incl: excl + vat };
}
