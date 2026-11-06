/** The same rules as the backend (modules/sales/domain/pricing.py): line discount, then the document discount,
 * then VAT on each net line; XOF has no cents, so only the totals are rounded, half up. */
export interface PricedLineInput {
  quantity: number;
  unit_price: number;
  discount_rate?: number;
  vat_rate?: number;
}

export interface SalesTotals {
  gross: number;
  discount: number;
  excl_tax: number;
  vat: number;
  incl_tax: number;
}

function roundHalfUp(value: number): number {
  return Math.sign(value) * Math.floor(Math.abs(value) + 0.5 + 1e-9);
}

export function lineNet(line: PricedLineInput, documentDiscount = 0): number {
  const gross = (Number(line.quantity) || 0) * (Number(line.unit_price) || 0);
  return gross * (1 - (Number(line.discount_rate) || 0) / 100) * (1 - (Number(documentDiscount) || 0) / 100);
}

export function computeTotals(lines: PricedLineInput[], documentDiscount = 0): SalesTotals {
  const gross = roundHalfUp(lines.reduce((sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.unit_price) || 0), 0));
  const excl = roundHalfUp(lines.reduce((sum, line) => sum + lineNet(line, documentDiscount), 0));
  const vat = roundHalfUp(lines.reduce((sum, line) => sum + (lineNet(line, documentDiscount) * (Number(line.vat_rate) || 0)) / 100, 0));
  return { gross, discount: gross - excl, excl_tax: excl, vat, incl_tax: excl + vat };
}

/** Line and document discounts combined, in %: 10 % then 5 % is 14.5 %. */
export function effectiveDiscount(lineDiscount: number, documentDiscount: number): number {
  return 100 - (100 - (Number(lineDiscount) || 0)) * (1 - (Number(documentDiscount) || 0) / 100);
}

/** The largest combined discount on any line, to warn before the server refuses it. */
export function largestDiscount(lines: PricedLineInput[], documentDiscount: number): number {
  return lines.reduce((worst, line) => Math.max(worst, effectiveDiscount(line.discount_rate ?? 0, documentDiscount)), Number(documentDiscount) || 0);
}
