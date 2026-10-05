import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScanLine } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useLabel } from "../production/shift/shiftText";
import { useShiftReferenceData } from "../production/shift/useShiftReferenceData";
import { listSessions, SCAN_SESSIONS_QUERY_KEY, type ScanSession, type SessionStatus } from "./scanApi";
import { S, SESSION_STATUS } from "./scanText";

type StatusFilter = "all" | SessionStatus;
const STATUS_VARIANT = { open: "warning", applied: "success", discarded: "default" } as const;

export function ScanSessionsTable({ onOpen }: { onOpen: (sessionId: string) => void }) {
  const { session } = useAuth();
  const label = useLabel();
  const reference = useShiftReferenceData(true);
  const lineName = (id: string) => reference.workCenters.find((w) => w.id === id)?.name ?? "—";
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const { data: sessions = [], isLoading } = useQuery({ queryKey: SCAN_SESSIONS_QUERY_KEY, queryFn: () => listSessions(session!.token) });

  const filterFields: FilterField<ScanSession>[] = [
    { key: "date", kind: "text", getValue: (s) => s.report_date },
    { key: "line", kind: "text", getValue: (s) => lineName(s.work_center_id) },
    { key: "shift", kind: "text", getValue: (s) => s.shift },
    { key: "pages", kind: "range", getValue: (s) => s.page_count ?? 0 },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const rows = columnFilters.apply(statusFilter === "all" ? sessions : sessions.filter((s) => s.status === statusFilter));

  const columns: ColumnDef<ScanSession>[] = [
    {
      key: "date", header: label(S.date), defaultWidth: 130, cell: (s) => s.report_date, sortValue: (s) => s.report_date,
      filterCell: { type: "text", value: columnFilters.text.date ?? "", onChange: (v) => columnFilters.setTextValue("date", v), placeholder: label(S.date) },
    },
    {
      key: "line", header: label(S.line), defaultWidth: 160, cell: (s) => lineName(s.work_center_id),
      filterCell: { type: "text", value: columnFilters.text.line ?? "", onChange: (v) => columnFilters.setTextValue("line", v), placeholder: label(S.line) },
    },
    {
      key: "shift", header: label(S.shift), defaultWidth: 120, cell: (s) => s.shift, sortValue: (s) => s.shift,
      filterCell: { type: "text", value: columnFilters.text.shift ?? "", onChange: (v) => columnFilters.setTextValue("shift", v), placeholder: label(S.shift) },
    },
    {
      key: "status", header: label(S.status), defaultWidth: 130,
      cell: (s) => <Badge variant={STATUS_VARIANT[s.status]}>{label(SESSION_STATUS[s.status])}</Badge>,
    },
    {
      key: "pages", header: label(S.pages), defaultWidth: 100, cell: (s) => s.page_count ?? 0, sortValue: (s) => s.page_count ?? 0,
      filterCell: {
        type: "range", min: columnFilters.range.pages?.min ?? "", max: columnFilters.range.pages?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("pages", "min", v), onMaxChange: (v) => columnFilters.setRangeValue("pages", "max", v),
      },
    },
    { key: "created", header: label(S.created), defaultWidth: 170, cell: (s) => new Date(s.created_at).toLocaleString(), sortValue: (s) => s.created_at },
    {
      key: "action", header: "", defaultWidth: 110, alwaysVisible: true, cellClassName: "text-right",
      cell: (s) => <Button size="sm" variant="outline" onClick={() => onOpen(s.id)}>{label(S.open)}</Button>,
    },
  ];
  const table = useTableColumns("scan.sessions", columns);
  const sorted = table.sortRows(rows);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <CardTitle>{label(S.sessions)}</CardTitle>
          <FilterTabs
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: "all", label: label(S.all) },
              { value: "open", label: label(SESSION_STATUS.open) },
              { value: "applied", label: label(SESSION_STATUS.applied) },
              { value: "discarded", label: label(SESSION_STATUS.discarded) },
            ]}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{label(S.clearFilters)}</Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table colWidths={table.colWidths}>
          <TableHeader>
            <TableRow>
              {table.visibleColumns.map((column) => (
                <ResizableTableHead
                  key={column.key}
                  width={table.getWidth(column.key)}
                  onResize={(width) => table.setWidth(column.key, width)}
                  sortDirection={table.sortDirectionFor(column.key)}
                  onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {isLoading && <TableLoadingRow colSpan={table.visibleColumns.length} />}
            {!isLoading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={table.visibleColumns.length} className="p-0">
                  <EmptyState icon={<ScanLine className="h-5 w-5" />} title={label(S.noSessions)} description="" />
                </TableCell>
              </TableRow>
            )}
            {sorted.map((row) => (
              <TableRow key={row.id}>
                {table.visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
