/** One way to bucket a table's rows for grouped display. */
export interface GroupSpec<Row> {
  key: string;
  label: string;
  getGroupKey: (row: Row) => string;
  getGroupLabel: (row: Row) => string;
}

export interface RowGroup<Row> {
  key: string;
  label: string;
  rows: Row[];
}

/**
 * Buckets rows into groups per `spec`, preserving each group's first-appearance
 * order in `rows` (which is already sorted/filtered by the caller). Passing
 * `undefined` returns every row in a single unlabeled group, so callers can
 * treat "no grouping" and "grouped" with the same rendering path.
 */
export function groupRows<Row>(rows: Row[], spec: GroupSpec<Row> | undefined): RowGroup<Row>[] {
  if (!spec) return [{ key: "__all__", label: "", rows }];
  const order: string[] = [];
  const groups = new Map<string, RowGroup<Row>>();
  for (const row of rows) {
    const key = spec.getGroupKey(row) || "—";
    let group = groups.get(key);
    if (!group) {
      group = { key, label: spec.getGroupLabel(row) || "—", rows: [] };
      groups.set(key, group);
      order.push(key);
    }
    group.rows.push(row);
  }
  return order.map((key) => groups.get(key)!);
}
