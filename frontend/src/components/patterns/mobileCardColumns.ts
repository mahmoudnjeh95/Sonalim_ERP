import type { ColumnDef } from "../../lib/useTableColumns";

export interface MobileCardLayout<Row> {
  /** The card's headline. */
  title: ColumnDef<Row>;
  /** Second line under the title, when there is a sensible one. */
  subtitle?: ColumnDef<Row>;
  /** Everything else, as label/value rows inside the card. */
  details: ColumnDef<Row>[];
  /** Actions/buttons, kept out of the detail list and pinned to the card's footer. */
  actions: ColumnDef<Row>[];
}

/** Columns whose cells are controls rather than data -- they belong in a footer, not a value row. */
function isActionColumn<Row>(column: ColumnDef<Row>): boolean {
  return column.mobileRole === "actions" || (column.mobileRole === undefined && ACTION_KEYS.has(column.key));
}

const ACTION_KEYS = new Set(["actions", "action", "rowActions", "menu"]);

/**
 * Picks which columns become a phone card's title, subtitle and detail rows.
 *
 * A table row laid out as a card needs a hierarchy that a table does not: one
 * headline, an optional second line, then the rest. The signal for that is
 * already in the column definitions, so no table has to re-describe itself:
 *
 *   1. an explicit `mobileRole` ("title" / "subtitle"), where a table needs to
 *      override the guess;
 *   2. otherwise `alwaysVisible` -- 68 of the 83 tables already mark their
 *      identifying column that way, and it means the same thing here;
 *   3. otherwise column order, which is how the table itself was written.
 *
 * Action columns never become the title, however they sort: a card headed by a
 * row of buttons tells the reader nothing.
 */
export function mobileCardLayout<Row>(visibleColumns: ColumnDef<Row>[]): MobileCardLayout<Row> | null {
  if (visibleColumns.length === 0) return null;

  const actions = visibleColumns.filter(isActionColumn);
  const content = visibleColumns.filter((column) => !isActionColumn(column));
  // A table of nothing but action columns has no headline to choose; show them
  // as the card body rather than promoting a button row to a title.
  if (content.length === 0) return { title: visibleColumns[0], details: [], actions: visibleColumns.slice(1) };

  const explicitTitle = content.find((column) => column.mobileRole === "title");
  const title = explicitTitle ?? content.find((column) => column.alwaysVisible) ?? content[0];

  const rest = content.filter((column) => column !== title);
  const explicitSubtitle = rest.find((column) => column.mobileRole === "subtitle");
  // Only promote a second `alwaysVisible` column to the subtitle -- otherwise the
  // first detail row is a better place for it, where it keeps its label.
  //
  // When the title was chosen explicitly, `alwaysVisible` is not evidence about
  // the subtitle: the column it displaced is usually an id the table had to keep
  // on screen, which reads better as a labelled detail than as a headline's
  // second line. So an explicit title takes an explicit subtitle or none.
  const subtitle = explicitTitle
    ? explicitSubtitle
    : (explicitSubtitle ?? rest.find((column) => column.alwaysVisible));

  return {
    title,
    subtitle,
    details: rest.filter((column) => column !== subtitle),
    actions,
  };
}
