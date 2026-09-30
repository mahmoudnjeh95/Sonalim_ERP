import { describe, expect, it } from "vitest";
import { mobileCardLayout } from "./mobileCardColumns";
import type { ColumnDef } from "../../lib/useTableColumns";

interface Row {
  id: string;
}

const col = (key: string, extra: Partial<ColumnDef<Row>> = {}): ColumnDef<Row> => ({
  key,
  header: key,
  cell: () => key,
  ...extra,
});

describe("mobileCardLayout", () => {
  it("returns null when there are no columns", () => {
    expect(mobileCardLayout<Row>([])).toBeNull();
  });

  it("uses the alwaysVisible column as the title, not the first column", () => {
    // The HR employees table: employee_no comes first, but `name` is the column
    // marked alwaysVisible and is what identifies the row to a reader.
    const layout = mobileCardLayout([col("employee_no"), col("name", { alwaysVisible: true }), col("department")]);
    expect(layout?.title.key).toBe("name");
    expect(layout?.details.map((c) => c.key)).toEqual(["employee_no", "department"]);
  });

  it("falls back to the first column when nothing is marked", () => {
    const layout = mobileCardLayout([col("reference"), col("amount")]);
    expect(layout?.title.key).toBe("reference");
    expect(layout?.subtitle).toBeUndefined();
    expect(layout?.details.map((c) => c.key)).toEqual(["amount"]);
  });

  it("promotes a second alwaysVisible column to the subtitle", () => {
    const layout = mobileCardLayout([
      col("code", { alwaysVisible: true }),
      col("label", { alwaysVisible: true }),
      col("qty"),
    ]);
    expect(layout?.title.key).toBe("code");
    expect(layout?.subtitle?.key).toBe("label");
    expect(layout?.details.map((c) => c.key)).toEqual(["qty"]);
  });

  it("lets an explicit mobileRole override the alwaysVisible guess", () => {
    const layout = mobileCardLayout([
      col("id", { alwaysVisible: true }),
      col("product", { mobileRole: "title" }),
      col("qty"),
    ]);
    expect(layout?.title.key).toBe("product");
    // The overridden column keeps its place in the details rather than vanishing.
    expect(layout?.details.map((c) => c.key)).toContain("id");
  });

  it("keeps an actions column out of the details and never makes it the title", () => {
    // `actions` is alwaysVisible in most tables, so without this it would win
    // the title and every card would be headed by a row of buttons.
    const layout = mobileCardLayout([col("actions", { alwaysVisible: true }), col("name"), col("qty")]);
    expect(layout?.title.key).toBe("name");
    expect(layout?.actions.map((c) => c.key)).toEqual(["actions"]);
    expect(layout?.details.map((c) => c.key)).toEqual(["qty"]);
  });

  it("recognises an actions column declared by mobileRole whatever its key", () => {
    const layout = mobileCardLayout([col("name", { alwaysVisible: true }), col("controls", { mobileRole: "actions" })]);
    expect(layout?.actions.map((c) => c.key)).toEqual(["controls"]);
    expect(layout?.details).toEqual([]);
  });

  it("does not lose a column: every input appears exactly once in the output", () => {
    const columns = [
      col("actions", { alwaysVisible: true }),
      col("code", { alwaysVisible: true }),
      col("label", { alwaysVisible: true }),
      col("qty"),
      col("date"),
    ];
    const layout = mobileCardLayout(columns)!;
    const out = [layout.title, ...(layout.subtitle ? [layout.subtitle] : []), ...layout.details, ...layout.actions];
    expect(out.map((c) => c.key).sort()).toEqual(columns.map((c) => c.key).sort());
  });

  it("handles a table that is only an actions column", () => {
    const layout = mobileCardLayout([col("actions", { alwaysVisible: true })]);
    expect(layout?.title.key).toBe("actions");
    expect(layout?.details).toEqual([]);
  });
});
