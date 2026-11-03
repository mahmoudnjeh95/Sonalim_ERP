import { describe, expect, it } from "vitest";
import { blankRow, isBlankRow, type GridRow } from "./ShiftGrid";
import { SECTION_BY_KEY } from "./sectionConfig";
import { followDefaults, partDefaults, toPayload, type Draft } from "./shiftModel";

const packingPart = SECTION_BY_KEY.packing.parts[0];
const runsPart = SECTION_BY_KEY.runs.parts[2];

describe("partDefaults", () => {
  it("starts a packing lot on the OF the shift's production ran", () => {
    const defaults = partDefaults(packingPart, null, null, "OF-1");
    expect(defaults.of_id).toBe("OF-1");
  });

  it("leaves the OF alone when no run has named one yet", () => {
    expect(partDefaults(packingPart, null, null, null).of_id).toBeUndefined();
  });

  it("does not put the packing OF on a table that has no OF of its own to default", () => {
    // The production rows name their own OF -- it is the thing being defaulted from.
    const defaults = partDefaults(runsPart, null, null, "OF-1");
    expect(defaults.of_id).toBeUndefined();
  });

  it("still carries the shift's lot", () => {
    expect(partDefaults(packingPart, "L-9", null, "OF-1")).toMatchObject({ lot_number: "L-9", of_id: "OF-1" });
  });
});

describe("a packing row started from the defaults", () => {
  it("is still a blank row: the screen wrote the OF, nobody typed it", () => {
    expect(isBlankRow(blankRow(undefined, partDefaults(packingPart, null, null, "OF-1")))).toBe(true);
  });

  it("is not sent to the server while nobody has typed in it", () => {
    const draft: Draft = { rows: [blankRow(undefined, partDefaults(packingPart, null, null, "OF-1"))] };
    expect(toPayload(SECTION_BY_KEY.packing, draft).rows).toEqual([]);
  });

  it("is sent, OF and all, once somebody types in it", () => {
    const row: GridRow = { ...blankRow(undefined, partDefaults(packingPart, null, null, "OF-1")), lot_number: "L-3" };
    const [sent] = toPayload(SECTION_BY_KEY.packing, { rows: [row] }).rows as Record<string, unknown>[];
    expect(sent).toMatchObject({ of_id: "OF-1", lot_number: "L-3" });
  });
});

describe("followDefaults", () => {
  it("moves the OF onto the lines nobody has typed in, when production names one later", () => {
    const draft: Draft = { rows: [blankRow(undefined, partDefaults(packingPart, null, null, null))] };
    const next = followDefaults(SECTION_BY_KEY.packing, draft, null, null, "OF-2");
    expect((next.rows as GridRow[])[0].of_id).toBe("OF-2");
  });

  it("leaves a line somebody started typing exactly as it is", () => {
    const typed: GridRow = { ...blankRow(undefined, {}), lot_number: "L-3", of_id: "OF-KEPT" };
    const next = followDefaults(SECTION_BY_KEY.packing, { rows: [typed] }, null, null, "OF-2");
    expect((next.rows as GridRow[])[0].of_id).toBe("OF-KEPT");
  });
});
