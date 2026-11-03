import { describe, expect, it } from "vitest";
import { pluralizeUnit } from "./units";

describe("pluralizeUnit", () => {
  it("pluralizes a unit written as a word, which agrees with the number in French", () => {
    expect(pluralizeUnit("pièce", 36)).toBe("pièces");
    expect(pluralizeUnit("carton", 12)).toBe("cartons");
  });

  it("leaves a symbol alone, because '36 kgs' is wrong", () => {
    expect(pluralizeUnit("kg", 36)).toBe("kg");
    expect(pluralizeUnit("L", 36)).toBe("L");
    expect(pluralizeUnit("kWh", 36)).toBe("kWh");
  });

  it("leaves a singular or zero quantity alone", () => {
    expect(pluralizeUnit("pièce", 1)).toBe("pièce");
    expect(pluralizeUnit("pièce", 0)).toBe("pièce");
  });

  it("does not pluralize a currency code", () => {
    // A currency code is an invariant ISO symbol, but "XOF" is three letters
    // and so matched the word test -- StatCard rendered "104 528 500 XOFs".
    expect(pluralizeUnit("XOF", 104528500)).toBe("XOF");
    expect(pluralizeUnit("EUR", 2)).toBe("EUR");
    expect(pluralizeUnit("USD", 1000)).toBe("USD");
  });
});
