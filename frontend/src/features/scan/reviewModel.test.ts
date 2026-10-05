import { describe, expect, it } from "vitest";
import { SECTIONS } from "../production/shift/sectionConfig";
import type { Proposal, ShiftState } from "./scanApi";
import {
  applyBody, mergeProposal, missingRequired, openDoubts, sectionsToWrite, valuesFromProposal,
} from "./reviewModel";

const proposal: Proposal = {
  header: { team: "Equipe D", conducteur: "Conducteur Un" },
  sections: {
    runs: { runs: [{ _scan_ref: "R1", of_id: null, lot_number: "D6249SNL", water_percentage: 28.9 }], versements: [] },
    packing: { rows: [{ _scan_ref: "K1", product_id: null, carton_quantity: 1 }] },
    stops: { stops: [{ _scan_ref: "S1", started_at: "2026-09-07T12:18", note: "coupure" }] },
  },
  flags: {
    "runs/runs/R1/lot_number": [{ reason: "lot_date", detail: "2026-09-06" }],
    "packing/rows/K1/carton_quantity": [{ reason: "lookalike", detail: null }],
    "stops/stops/S1/note": [{ reason: "low_confidence", detail: null }],
    "runs/-/-/-": [{ reason: "rows_disagree", detail: null }],
  },
  sources: {},
  coded: {},
  set_aside: {},
  pages: {},
};

const shiftWithStops: ShiftState = {
  id: "SH", status: "open", team: null, conducteur: null, agent_fabrication: null, machiniste: null, aide_machiniste: null,
  default_lot_number: null,
  sections: { stops: { status: "submitted", revision: 1, rows: 2, fingerprint: "fp-stops", payload: {} } },
};

describe("reviewModel", () => {
  it("keys every row by its scan reference", () => {
    const values = valuesFromProposal(proposal);
    expect((values.sections.runs!.runs as { _key: string }[])[0]._key).toBe("R1");
    expect(values.header.team).toBe("Equipe D");
  });

  it("keeps touched sections and typed names when a new photo is read", () => {
    const current = valuesFromProposal(proposal);
    (current.sections.stops!.stops as Record<string, unknown>[])[0].note = "typed";
    current.header.conducteur = "Racine";
    const merged = mergeProposal(current, proposal, new Set(["stops"]));
    expect((merged.sections.stops!.stops as Record<string, unknown>[])[0].note).toBe("typed");
    expect(merged.header.conducteur).toBe("Racine");
  });

  it("counts a doubt until the value is changed or confirmed, only in written sections", () => {
    const values = valuesFromProposal(proposal);
    expect(openDoubts(proposal, values, new Set(), ["runs", "packing"]).sort()).toEqual([
      "packing/rows/K1/carton_quantity", "runs/runs/R1/lot_number",
    ]);
    (values.sections.packing!.rows as Record<string, unknown>[])[0].carton_quantity = 2;
    expect(openDoubts(proposal, values, new Set(["runs/runs/R1/lot_number"]), ["runs", "packing"])).toEqual([]);
  });

  it("tells blocking required values from those needed at submit", () => {
    const missing = missingRequired(valuesFromProposal(proposal), SECTIONS, ["runs", "packing"]);
    expect(missing.map((m) => [m.section, m.column.key, m.blocking])).toEqual([
      ["runs", "of_id", true],
      ["packing", "product_id", false],
    ]);
  });

  it("writes a section already filled only when replace is chosen", () => {
    const values = valuesFromProposal(proposal);
    expect(sectionsToWrite(values, {}, shiftWithStops)).toEqual(["runs", "packing"]);
    expect(sectionsToWrite(values, { stops: "replace" }, shiftWithStops)).toEqual(["runs", "stops", "packing"]);
  });

  it("builds the apply body without client keys or blank rows", () => {
    const values = valuesFromProposal(proposal);
    (values.sections.stops!.stops as Record<string, unknown>[]).push({ _key: "blank", _fresh: true });
    const body = applyBody(values, ["stops"], shiftWithStops);
    expect(body.sections.stops).toEqual({ stops: [{ _scan_ref: "S1", started_at: "2026-09-07T12:18", note: "coupure" }] });
    expect(body.fingerprints).toEqual({ stops: "fp-stops" });
    expect(body.header.team).toBe("Equipe D");
  });
});
