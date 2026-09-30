import { describe, expect, it } from "vitest";
import { evaluateQuantity, isSum, shouldSyncText } from "./quantityExpression";

describe("evaluateQuantity", () => {
  it("reads a comma as the decimal point, the way a French keyboard types it", () => {
    expect(evaluateQuantity("100,5")).toBe(100.5);
    expect(evaluateQuantity("15,67+15,27")).toBe(30.94);
  });

  it("refuses a half-typed figure rather than saving the part before the separator", () => {
    expect(evaluateQuantity("100,")).toBeNull();
    expect(evaluateQuantity("15,67+")).toBeNull();
  });
});

describe("shouldSyncText", () => {
  it("leaves a comma-typed figure alone: the box says the value already", () => {
    // 100,5 evaluates to 100.5 -- rewriting the box to "100.5" would eat the comma
    // under the cursor, which is what stopped anyone typing 100,5 KG of film.
    expect(shouldSyncText("100,5", 100.5)).toBe(false);
  });

  it("leaves a figure still being typed alone", () => {
    expect(shouldSyncText("100,", 100)).toBe(false);
    expect(shouldSyncText("15,67+", 15.67)).toBe(false);
  });

  it("leaves a comma-typed sum alone", () => {
    expect(shouldSyncText("15,67+15,27", 30.94)).toBe(false);
  });

  it("follows the form when the value really moved (a draft loading in)", () => {
    expect(shouldSyncText("100,5", 42)).toBe(true);
    expect(shouldSyncText("", 42)).toBe(true);
  });

  it("does not write a 0 into a box somebody just emptied", () => {
    expect(shouldSyncText("", 0)).toBe(false);
  });

  it("ignores a value that is not a number", () => {
    expect(shouldSyncText("100,5", Number.NaN)).toBe(false);
  });
});

describe("isSum", () => {
  it("sees a sum typed with commas", () => {
    expect(isSum("15,67+15,27")).toBe(true);
    expect(isSum("100,5")).toBe(false);
  });
});
