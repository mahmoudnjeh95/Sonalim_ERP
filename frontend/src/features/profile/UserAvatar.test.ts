import { describe, expect, it } from "vitest";
import { initialsOf } from "./UserAvatar";

describe("initialsOf", () => {
  it("takes the first and last name of a full name", () => {
    expect(initialsOf("Awa Traoré", "awa@sonalim.local")).toBe("AT");
  });

  it("ignores the middle names", () => {
    expect(initialsOf("Awa Fatoumata Traoré", null)).toBe("AT");
  });

  it("takes two letters when there is only one word", () => {
    expect(initialsOf("Awa", null)).toBe("AW");
  });

  it("falls back to the e-mail when no name is kept for the account", () => {
    expect(initialsOf(null, "demo@sonalim-erp.local")).toBe("DE");
  });

  it("reads a dotted e-mail as two names", () => {
    expect(initialsOf(null, "awa.traore@sonalim-erp.local")).toBe("AT");
  });

  it("never renders empty, even with nothing to go on", () => {
    expect(initialsOf(null, null)).toBe("?");
    expect(initialsOf("   ", "")).toBe("?");
  });
});
