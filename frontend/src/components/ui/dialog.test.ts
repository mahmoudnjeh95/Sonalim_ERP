import { describe, expect, it } from "vitest";
import { twMerge } from "tailwind-merge";
import { widthCapsToDesktop } from "./dialog";

// What DialogContent puts in front of the caller's classes.
const SHEET_BASE = "w-full inset-x-0 bottom-0 max-w-none rounded-t-xl sm:max-w-md sm:rounded-xl";

const merged = (callerClassName?: string) => twMerge(SHEET_BASE, widthCapsToDesktop(callerClassName));

describe("widthCapsToDesktop", () => {
  it("moves a plain max-w cap to its sm: variant", () => {
    expect(widthCapsToDesktop("max-w-2xl")).toBe("sm:max-w-2xl");
  });

  it("leaves w-full and w-auto alone", () => {
    // These are layout, not a desktop width cap -- the sheet wants w-full on a phone.
    expect(widthCapsToDesktop("w-full")).toBe("w-full");
    expect(widthCapsToDesktop("w-auto")).toBe("w-auto");
  });

  it("does not touch classes that are not widths", () => {
    expect(widthCapsToDesktop("p-0 gap-2 overflow-hidden")).toBe("p-0 gap-2 overflow-hidden");
  });

  it("leaves an already-prefixed width as it is", () => {
    expect(widthCapsToDesktop("sm:max-w-2xl")).toBe("sm:max-w-2xl");
  });

  it("handles undefined", () => {
    expect(widthCapsToDesktop(undefined)).toBeUndefined();
  });

  it("keeps the phone sheet full width even when the caller caps the width", () => {
    // The bug this exists to prevent: an unprefixed max-w-2xl would otherwise
    // knock out the sheet's max-w-none and leave a narrow box on a phone.
    for (const caller of ["max-w-2xl", "max-w-lg", "max-w-5xl", "max-w-md"]) {
      expect(merged(caller)).toContain("max-w-none");
    }
  });

  it("still applies the caller's width on desktop, overriding the default", () => {
    const result = merged("max-w-2xl");
    expect(result).toContain("sm:max-w-2xl");
    // The sheet's own sm:max-w-md must lose to the caller's, not sit alongside it.
    expect(result).not.toContain("sm:max-w-md");
  });

  it("keeps the default desktop width when the caller sets none", () => {
    expect(merged(undefined)).toContain("sm:max-w-md");
  });
});
