import { describe, expect, it } from "vitest";
import { computeTotals } from "./invoiceMath";

describe("computeTotals", () => {
  it("applies the discount before VAT and rounds the totals to the franc, like the server", () => {
    const totals = computeTotals(
      [
        { quantity: 3, unit_price: 1000, discount_rate: 10, vat_rate: 18 },
        { quantity: 1, unit_price: 333.33, vat_rate: 0 },
      ],
      18,
    );
    expect(totals).toEqual({ gross: 3333, discount: 300, excl: 3033, vat: 486, incl: 3519 });
  });

  it("uses the tenant's default rate for a line without one", () => {
    expect(computeTotals([{ quantity: 1, unit_price: 1000, vat_rate: null }], 5).vat).toBe(50);
  });

  it("rounds VAT on the total, not per line", () => {
    const lines = Array.from({ length: 4 }, () => ({ quantity: 1, unit_price: 10.25, vat_rate: 18 }));
    expect(computeTotals(lines, 18)).toMatchObject({ excl: 41, vat: 7, incl: 48 });
  });
});
