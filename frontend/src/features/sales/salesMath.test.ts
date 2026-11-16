import { describe, expect, it } from "vitest";
import { computeTotals, effectiveDiscount, largestDiscount } from "./salesMath";

describe("computeTotals", () => {
  it("applies the line discount, then the document discount, then VAT, like the server", () => {
    const totals = computeTotals(
      [
        { quantity: 10, unit_price: 1000, discount_rate: 10, vat_rate: 18 },
        { quantity: 3, unit_price: 333, discount_rate: 0, vat_rate: 0 },
      ],
      5,
    );
    expect(totals).toEqual({ gross: 10999, discount: 1500, excl_tax: 9499, vat: 1539, incl_tax: 11038 });
  });

  it("rounds only the totals, half up", () => {
    expect(computeTotals([{ quantity: 4, unit_price: 855, vat_rate: 18 }]).vat).toBe(616);
    expect(computeTotals([{ quantity: 2, unit_price: 9.99 }]).incl_tax).toBe(20);
  });
});

describe("discounts", () => {
  it("compounds line and document discounts", () => {
    expect(effectiveDiscount(10, 5)).toBeCloseTo(14.5);
    expect(largestDiscount([{ quantity: 1, unit_price: 1, discount_rate: 8 }], 5)).toBeCloseTo(12.6);
    expect(largestDiscount([], 7)).toBe(7);
  });
});
