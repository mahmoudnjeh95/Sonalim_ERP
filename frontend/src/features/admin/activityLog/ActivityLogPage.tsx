import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, Lock } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Skeleton } from "../../../components/ui/skeleton";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { humanizeAuditAction, humanizeSnakeCase } from "../../../lib/humanize";
import { listAuditLog, type AuditLogEntry } from "./api";

const PAGE_SIZE = 300;

const VIEW_PERMISSION = "core.view_audit_log";

function formatWhen(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "medium" });
}

/**
 * A payload key ending in `_id` (or bare `id`) points at another record's raw
 * ULID -- exactly what this app never shows a user (see StockMoveDetailDialog,
 * the warehouse move-reference work). There's no name lookup available here
 * for an arbitrary payload across ~100 action types, so the id is dropped
 * rather than shown raw; whatever human-readable sibling field the action
 * logged alongside it (a code, a status, a count) still comes through.
 */
function isRawIdKey(key: string): boolean {
  return key === "id" || key.endsWith("_id");
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Same id-dropping, key-humanizing treatment as the top level, applied recursively -- for a
 * payload value that's itself a nested object or array (a line-item list, a before/after snapshot). */
function stripIdsDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripIdsDeep);
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [key, v] of Object.entries(value)) {
      if (isRawIdKey(key)) continue;
      out[humanizeSnakeCase(key)] = stripIdsDeep(v);
    }
    return out;
  }
  return value;
}

function formatPayloadValue(value: unknown, language: string, yesLabel: string, noLabel: string): React.ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? yesLabel : noLabel;
  if (typeof value === "number") return new Intl.NumberFormat(language === "fr" ? "fr-FR" : "en-US").format(value);
  if (typeof value === "string") {
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) || /^\d{4}-\d{2}-\d{2}$/.test(value)) {
      const parsed = new Date(value);
      if (!Number.isNaN(parsed.getTime())) {
        return parsed.toLocaleString(language === "fr" ? "fr-FR" : "en-US", {
          dateStyle: "medium",
          timeStyle: value.includes("T") ? "short" : undefined,
        });
      }
    }
    return humanizeSnakeCase(value);
  }
  if ((Array.isArray(value) && value.length === 0) || (isPlainObject(value) && Object.keys(value).length === 0)) return "—";
  // A nested list or record (e.g. a report's line items) has no generic one-line
  // rendering -- pretty-printing the id-stripped, key-humanized version is the
  // best a payload-shape-agnostic formatter can do without hardcoding every action.
  return (
    <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-left font-mono text-xs text-muted-foreground">
      {JSON.stringify(stripIdsDeep(value), null, 2)}
    </pre>
  );
}

interface PayloadChange {
  key: string;
  before: unknown;
  after: unknown;
}

/** Shallow field-by-field diff, used for the common "before"/"after" snapshot pattern
 * (corrections/revisions across production reports, conditionnement, stock admin edits)
 * -- showing only what changed reads far better than two full record dumps side by side. */
function diffPlainObjects(before: Record<string, unknown>, after: Record<string, unknown>): PayloadChange[] {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const changes: PayloadChange[] = [];
  for (const key of keys) {
    if (isRawIdKey(key)) continue;
    const b = before[key];
    const a = after[key];
    if (JSON.stringify(b) !== JSON.stringify(a)) changes.push({ key, before: b, after: a });
  }
  return changes;
}

export function ActivityLogPage() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [detailsEntry, setDetailsEntry] = useState<AuditLogEntry | null>(null);

  const canView = hasPermission(VIEW_PERMISSION);

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["core", "audit-log", "all", limit] as const,
    queryFn: () => listAuditLog(token, { limit }),
    enabled: canView,
  });

  const columnFilterFields: FilterField<AuditLogEntry>[] = [
    { key: "who", kind: "text", getValue: (entry) => entry.actor_email ?? entry.actor_id },
    { key: "action", kind: "text", getValue: (entry) => humanizeAuditAction(entry.action) },
    { key: "entityType", kind: "text", getValue: (entry) => humanizeSnakeCase(entry.entity_type) },
    { key: "entityId", kind: "text", getValue: (entry) => entry.entity_id },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredEntries = columnFilters.apply(entries);

  const columns: ColumnDef<AuditLogEntry>[] = [
    {
      key: "when",
      header: t("admin.activityLog.column.when"),
      defaultWidth: 200,
      cell: (entry) => <span className="whitespace-nowrap text-muted-foreground">{formatWhen(entry.occurred_at, language)}</span>,
      sortValue: (entry) => entry.occurred_at,
    },
    {
      key: "who",
      header: t("admin.activityLog.column.who"),
      defaultWidth: 200,
      cell: (entry) => <span className="whitespace-nowrap">{entry.actor_email ?? entry.actor_id}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.who ?? "",
        onChange: (v) => columnFilters.setTextValue("who", v),
        placeholder: t("admin.activityLog.column.who"),
      },
      sortValue: (entry) => entry.actor_email ?? entry.actor_id,
    },
    {
      key: "action",
      header: t("admin.activityLog.column.action"),
      defaultWidth: 260,
      cell: (entry) => <span className="font-medium">{humanizeAuditAction(entry.action)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.action ?? "",
        onChange: (v) => columnFilters.setTextValue("action", v),
        placeholder: t("admin.activityLog.column.action"),
      },
      sortValue: (entry) => humanizeAuditAction(entry.action),
    },
    {
      key: "entityType",
      header: t("admin.activityLog.column.entityType"),
      defaultWidth: 180,
      cell: (entry) => <span className="text-muted-foreground">{humanizeSnakeCase(entry.entity_type)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.entityType ?? "",
        onChange: (v) => columnFilters.setTextValue("entityType", v),
        placeholder: t("admin.activityLog.column.entityType"),
      },
      sortValue: (entry) => humanizeSnakeCase(entry.entity_type),
    },
    {
      key: "entityId",
      header: t("admin.activityLog.column.entityId"),
      defaultWidth: 200,
      cell: (entry) => <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">{entry.entity_id}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.entityId ?? "",
        onChange: (v) => columnFilters.setTextValue("entityId", v),
        placeholder: t("admin.activityLog.column.entityId"),
      },
      sortValue: (entry) => entry.entity_id,
    },
    {
      key: "details",
      header: t("admin.activityLog.column.details"),
      defaultWidth: 120,
      cell: (entry) => (
        <Button variant="ghost" size="sm" onClick={() => setDetailsEntry(entry)}>
          {t("admin.activityLog.viewDetails")}
        </Button>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("admin.activityLog", columns);
  const sortedEntries = sortRows(filteredEntries);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{t("admin.activityLog.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.activityLog.subtitle")}</p>
      </div>

      {!canView ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={<Lock className="h-5 w-5" />}
              title={t("admin.activityLog.noAccess.title")}
              description={t("admin.activityLog.noAccess.description")}
            />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle>{t("admin.activityLog.table.title")}</CardTitle>
                <CardDescription>{t("admin.activityLog.table.subtitle")}</CardDescription>
              </div>
              <div className="flex items-center gap-2">
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
                <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <Table colWidths={colWidths}>
              <TableHeader>
                <TableRow>
                  {visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={getWidth(column.key)}
                      onResize={(width) => setWidth(column.key, width)}
                      className={column.headerClassName}
                      sortDirection={sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
                <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
              </TableHeader>
              <TableBody>
                {isLoading &&
                  Array.from({ length: 6 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={visibleColumns.length}>
                        <Skeleton className="h-5 w-full" />
                      </TableCell>
                    </TableRow>
                  ))}
                {!isLoading && filteredEntries.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={visibleColumns.length} className="p-0">
                      <EmptyState
                        icon={<History className="h-5 w-5" />}
                        title={t("admin.activityLog.empty.title")}
                        description={t("admin.activityLog.empty.description")}
                      />
                    </TableCell>
                  </TableRow>
                )}
                {sortedEntries.map((entry) => (
                  <TableRow key={entry.id}>
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(entry)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
          <div className="flex justify-center border-t border-border py-3">
            <Button variant="outline" size="sm" onClick={() => setLimit((prev) => prev + PAGE_SIZE)} disabled={isLoading || entries.length < limit}>
              {t("admin.activityLog.loadMore")}
            </Button>
          </div>
        </Card>
      )}

      <Dialog open={detailsEntry != null} onOpenChange={(open) => !open && setDetailsEntry(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("admin.activityLog.details.title")}</DialogTitle>
            <DialogDescription>{detailsEntry ? humanizeAuditAction(detailsEntry.action) : ""}</DialogDescription>
          </DialogHeader>
          {(() => {
            const payload = detailsEntry?.payload ?? {};
            const before = payload.before;
            const after = payload.after;
            const hasSnapshotDiff = isPlainObject(before) && isPlainObject(after);
            const rows = Object.entries(payload).filter(
              ([key]) => !isRawIdKey(key) && !(hasSnapshotDiff && (key === "before" || key === "after")),
            );
            const changes = hasSnapshotDiff ? diffPlainObjects(before as Record<string, unknown>, after as Record<string, unknown>) : [];

            if (rows.length === 0 && !hasSnapshotDiff) {
              return <p className="text-sm text-muted-foreground">{t("admin.activityLog.details.empty")}</p>;
            }
            return (
              <div className="space-y-4">
                {rows.length > 0 && (
                  <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-lg border border-border p-4 sm:grid-cols-2">
                    {rows.map(([key, value]) => (
                      <div key={key} className="flex items-baseline justify-between gap-3">
                        <dt className="text-sm text-muted-foreground">{humanizeSnakeCase(key)}</dt>
                        <dd className="min-w-0 break-words text-right text-sm font-medium">
                          {formatPayloadValue(value, language, t("common.yes"), t("common.no"))}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                {hasSnapshotDiff && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {t("admin.activityLog.details.changes")}
                    </p>
                    {changes.length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t("admin.activityLog.details.noChanges")}</p>
                    ) : (
                      <ul className="space-y-1.5">
                        {changes.map((change) => (
                          <li key={change.key} className="rounded-lg border border-border p-2.5 text-sm">
                            <div className="font-medium">{humanizeSnakeCase(change.key)}</div>
                            <div className="mt-1 flex flex-wrap items-center gap-2">
                              <span className="text-muted-foreground line-through">
                                {formatPayloadValue(change.before, language, t("common.yes"), t("common.no"))}
                              </span>
                              <span className="text-muted-foreground">→</span>
                              <span>{formatPayloadValue(change.after, language, t("common.yes"), t("common.no"))}</span>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}
