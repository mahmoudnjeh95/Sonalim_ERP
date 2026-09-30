import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookA, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useLabel } from "../production/shift/shiftText";
import { deleteAlias, getVocabulary, listAliases, SCAN_ALIASES_QUERY_KEY, updateAlias, type Alias } from "./scanApi";
import { KIND_LABELS, S } from "./scanText";

export function AliasesTable() {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const canEdit = hasPermission("scan.admin_aliases");
  const [kind, setKind] = useState<string>("all");
  const [editing, setEditing] = useState<Alias | null>(null);
  const [target, setTarget] = useState("");
  const { data: aliases = [], isLoading } = useQuery({ queryKey: SCAN_ALIASES_QUERY_KEY, queryFn: () => listAliases(token) });
  const vocabulary = useQuery({ queryKey: ["scan", "vocabulary", "all"], queryFn: () => getVocabulary(token) });
  const valueLabel = (alias: Alias) =>
    vocabulary.data?.[alias.kind]?.find((option) => option.value === alias.target_value)?.label ?? alias.target_value;
  const refresh = () => queryClient.invalidateQueries({ queryKey: SCAN_ALIASES_QUERY_KEY });
  const fail = (error: unknown) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined });
  const save = useMutation({
    mutationFn: () => updateAlias(token, editing!.id, target),
    onSuccess: () => { refresh(); setEditing(null); },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteAlias(token, id), onSuccess: refresh, onError: fail });

  const filterFields: FilterField<Alias>[] = [
    { key: "written", kind: "text", getValue: (a) => a.raw_text_example },
    { key: "value", kind: "text", getValue: (a) => valueLabel(a) },
    { key: "uses", kind: "range", getValue: (a) => a.use_count },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const rows = columnFilters.apply(kind === "all" ? aliases : aliases.filter((a) => a.kind === kind));
  const kinds = [...new Set(aliases.map((a) => a.kind))];

  const columns: ColumnDef<Alias>[] = [
    { key: "kind", header: label(S.kind), defaultWidth: 170, cell: (a) => <Badge variant="outline">{label(KIND_LABELS[a.kind] ?? S.kind)}</Badge> },
    {
      key: "written", header: label(S.written), defaultWidth: 200, cell: (a) => <span className="font-medium">{a.raw_text_example}</span>,
      sortValue: (a) => a.raw_text_normalized,
      filterCell: { type: "text", value: columnFilters.text.written ?? "", onChange: (v) => columnFilters.setTextValue("written", v), placeholder: label(S.written) },
    },
    {
      key: "value", header: label(S.value), defaultWidth: 240, cell: valueLabel, sortValue: valueLabel,
      filterCell: { type: "text", value: columnFilters.text.value ?? "", onChange: (v) => columnFilters.setTextValue("value", v), placeholder: label(S.value) },
    },
    {
      key: "uses", header: label(S.uses), defaultWidth: 110, cell: (a) => a.use_count, sortValue: (a) => a.use_count,
      filterCell: {
        type: "range", min: columnFilters.range.uses?.min ?? "", max: columnFilters.range.uses?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("uses", "min", v), onMaxChange: (v) => columnFilters.setRangeValue("uses", "max", v),
      },
    },
    { key: "updated", header: label(S.updated), defaultWidth: 170, cell: (a) => new Date(a.updated_at).toLocaleString(), sortValue: (a) => a.updated_at },
    {
      key: "action", header: "", defaultWidth: 180, alwaysVisible: true, cellClassName: "text-right",
      cell: (a) =>
        canEdit ? (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="outline" onClick={() => { setEditing(a); setTarget(a.target_value); }}>
              <Pencil className="h-3.5 w-3.5" />
              {label(S.edit)}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => window.confirm(label(S.deleteConfirm)) && remove.mutate(a.id)} aria-label={label(S.delete)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null,
    },
  ];
  const table = useTableColumns("scan.aliases", columns);
  const sorted = table.sortRows(rows);
  const choices = editing ? vocabulary.data?.[editing.kind] ?? [] : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{label(S.viewDictionary)}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{label(S.dictionaryHint)}</p>
          </div>
          <FilterTabs
            value={kind}
            onChange={setKind}
            options={[{ value: "all", label: label(S.all) }, ...kinds.map((k) => ({ value: k, label: label(KIND_LABELS[k] ?? S.kind) }))]}
          />
          {columnFilters.isActive && <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{label(S.clearFilters)}</Button>}
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
                  <EmptyState icon={<BookA className="h-5 w-5" />} title={label(S.noAliases)} description="" />
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

      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{`${label(S.edit)} — ${editing?.raw_text_example ?? ""}`}</DialogTitle>
          </DialogHeader>
          {choices.length > 0 ? (
            <Select value={target} onChange={(e) => setTarget(e.target.value)}>
              {choices.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </Select>
          ) : (
            <Input value={target} onChange={(e) => setTarget(e.target.value)} />
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setEditing(null)}>{label(S.cancel)}</Button>
            <Button onClick={() => save.mutate()} disabled={!target.trim() || save.isPending}>{label(S.save)}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
