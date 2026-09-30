import { Fragment, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { ChevronRight, Plus, X } from "lucide-react";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { QuantityExpressionInput } from "../../../components/patterns/QuantityExpressionInput";
import { cn } from "../../../lib/utils";
import type { Column, ChildDef, OptionSource } from "./sectionConfig";
import type { Row } from "./shiftApi";
import { T, useLabel } from "./shiftText";

export interface Option {
  value: string;
  label: string;
}
export type OptionMap = Record<OptionSource, Option[]>;

/** How a cell is marked by a screen reviewing values it did not type (the paper scan). */
export interface CellDecor {
  tone: "doubt" | "required";
  title?: string;
}

export const DECOR_CLASS: Record<CellDecor["tone"], string> = {
  doubt: "bg-warning-soft ring-1 ring-inset ring-warning/60",
  required: "ring-1 ring-inset ring-destructive",
};

/**
 * A row being edited: the backend's row plus client-only fields -- a key, a flag for a row
 * just added, and the fields that hold a default nobody has typed over (`_auto`).
 */
export type GridRow = Row & { _key: string; _fresh?: boolean; _auto?: string[] };

export const newKey = () => Math.random().toString(36).slice(2, 10);

/**
 * A line nobody has typed in: no figure in any field. Client keys, an empty child list and a
 * default nobody has typed over do not count -- a lot the screen wrote is not somebody's entry.
 */
export function isBlankRow(row: GridRow): boolean {
  return Object.entries(row).every(([key, value]) => {
    if (key.startsWith("_") || row._auto?.includes(key)) return true;
    if (Array.isArray(value)) return value.length === 0;
    return value === null || value === undefined || value === "";
  });
}

/** A row that starts with `defaults` in it; they stay the screen's, not the team's, until a cell is typed in. */
export function withDefaults(row: GridRow, defaults: Row): GridRow {
  const keys = Object.keys(defaults);
  const cleared = Object.fromEntries((row._auto ?? []).map((key) => [key, null]));
  return { ...row, ...cleared, ...defaults, _auto: keys.length > 0 ? keys : undefined };
}

/** A fresh empty line, with an empty child list when the table has child lines. */
export function blankRow(childKey?: string, defaults: Row = {}): GridRow {
  const row: GridRow = withDefaults({ _key: newKey(), _fresh: true }, defaults);
  if (childKey) row[childKey] = [];
  return row;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO instant -> the local `YYYY-MM-DDTHH:mm` a datetime-local box wants. */
function toLocalInput(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** A local `YYYY-MM-DDTHH:mm` -> an unambiguous ISO instant, so the server's time zone never matters. */
function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

const asText = (value: unknown) => (value === null || value === undefined ? "" : String(value));

/** Where a column starts, in pixels; the team can drag it wider or narrower. */
const DEFAULT_WIDTH: Record<Column["kind"], number> = {
  text: 136,
  number: 96,
  int: 88,
  time: 108,
  date: 140,
  datetime: 192,
  select: 168,
  expression: 124,
  readonly: 150,
};
const MIN_WIDTH = 60;
const MAX_WIDTH = 480;
const CONTROL_WIDTH = 36;
const clampWidth = (px: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(px)));
const STORAGE_PREFIX = "sonalim-erp.shift-columns.";

function readWidths(storageKey?: string): Record<string, number> {
  if (!storageKey) return {};
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + storageKey);
    const parsed = raw ? (JSON.parse(raw) as Record<string, number>) : {};
    return Object.fromEntries(Object.entries(parsed).filter(([, v]) => typeof v === "number").map(([k, v]) => [k, clampWidth(v)]));
  } catch {
    // Blocked or private storage: the widths just do not persist.
    return {};
  }
}

function writeWidths(storageKey: string | undefined, widths: Record<string, number>) {
  if (!storageKey) return;
  try {
    if (Object.keys(widths).length === 0) localStorage.removeItem(STORAGE_PREFIX + storageKey);
    else localStorage.setItem(STORAGE_PREFIX + storageKey, JSON.stringify(widths));
  } catch {
    // see readWidths
  }
}

function useColumnWidths(storageKey: string | undefined, columns: Column[]) {
  const [widths, setWidths] = useState<Record<string, number>>(() => readWidths(storageKey));
  const widthOf = (column: Column) => widths[column.key] ?? DEFAULT_WIDTH[column.kind];
  const setWidth = (column: Column, px: number) =>
    setWidths((current) => {
      const next = { ...current, [column.key]: clampWidth(px) };
      writeWidths(storageKey, next);
      return next;
    });
  const resetOne = (column: Column) =>
    setWidths((current) => {
      const { [column.key]: _dropped, ...rest } = current;
      void _dropped;
      writeWidths(storageKey, rest);
      return rest;
    });
  const resetAll = () => {
    setWidths({});
    writeWidths(storageKey, {});
  };
  const total = columns.reduce((sum, column) => sum + widthOf(column), 0);
  return { widthOf, setWidth, resetOne, resetAll, total, customised: Object.keys(widths).length > 0 };
}

/** The drag handle on a header's right edge: pointer drag, arrow keys, double-click to reset. */
function ResizeHandle({
  width,
  onResize,
  onReset,
  label,
}: {
  width: number;
  onResize: (px: number) => void;
  onReset: () => void;
  label: string;
}) {
  const [drag, setDrag] = useState<{ startX: number; startWidth: number } | null>(null);
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      tabIndex={0}
      title={label}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        setDrag({ startX: event.clientX, startWidth: width });
      }}
      onPointerMove={(event) => {
        if (drag) onResize(drag.startWidth + event.clientX - drag.startX);
      }}
      onPointerUp={() => setDrag(null)}
      onPointerCancel={() => setDrag(null)}
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onResize(width - 12);
        else if (event.key === "ArrowRight") onResize(width + 12);
        else return;
        event.preventDefault();
      }}
      className={cn(
        "absolute right-0 top-0 z-[2] h-full w-2 cursor-col-resize touch-none select-none transition-colors hover:bg-primary/25 focus-visible:bg-primary/40 focus-visible:outline-none",
        drag && "bg-primary/40",
      )}
    />
  );
}

const inputClass = "h-8 px-2 text-xs";

export function Cell({
  column,
  value,
  onChange,
  options,
  disabled,
  idPrefix,
  row,
}: {
  column: Column;
  value: unknown;
  onChange: (value: unknown) => void;
  options: OptionMap;
  disabled?: boolean;
  idPrefix: string;
  /** The row being edited, for columns whose choices depend on it. */
  row?: Row;
}) {
  const label = useLabel();
  const name = label(column.label);
  const id = `${idPrefix}-${column.key}`;

  switch (column.kind) {
    case "select": {
      const list = column.optionsFor && row ? column.optionsFor(row, options) : column.options ? options[column.options] : [];
      const current = asText(value);
      // A value the list no longer offers (a retired kind, or a classification gap): fall back to its
      // name from the full products list rather than showing the raw id.
      const fallbackLabel = current && !list.some((option) => option.value === current)
        ? options.products.find((option) => option.value === current)?.label ?? current
        : null;
      return (
        <Select
          id={id}
          aria-label={name}
          className={cn(inputClass, "w-full py-0")}
          value={current}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value || null)}
        >
          <option value="">{label(T.choose)}</option>
          {list.length === 0 && column.emptyHint ? <option disabled>{label(column.emptyHint)}</option> : null}
          {fallbackLabel !== null ? <option value={current}>{fallbackLabel}</option> : null}
          {list.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      );
    }
    case "readonly":
      return (
        <div id={id} aria-label={name} className="flex h-8 w-full items-center px-2 text-xs text-muted-foreground">
          {(column.valueFor && row ? column.valueFor(row, options) : null) || asText(value) || "—"}
        </div>
      );
    case "number":
    case "int": {
      const scale = column.scale ?? 1;
      const shown = scale === 1 ? asText(value) : asText(typeof value === "number" ? value * scale : value === "" || value == null ? value : Number(value) * scale);
      return (
        <Input
          id={id}
          aria-label={name}
          inputMode="decimal"
          disabled={disabled}
          className={cn(inputClass, "w-full text-right tabular-nums", shown === "0" && "text-muted-foreground")}
          value={shown}
          // A French keyboard types a comma; the server reads a point.
          onChange={(event) => {
            const typed = event.target.value.replace(",", ".");
            if (scale === 1) return onChange(typed);
            const parsed = Number(typed);
            onChange(typed === "" ? "" : Number.isFinite(parsed) ? String(parsed / scale) : typed);
          }}
        />
      );
    }
    case "expression":
      return (
        <div className="w-full">
          <QuantityExpressionInput
            id={id}
            value={Number(value) || 0}
            onValueChange={(next) => onChange(Number.isFinite(next) ? next : 0)}
          />
        </div>
      );
    case "time":
      return (
        <Input
          id={id}
          aria-label={name}
          type="time"
          disabled={disabled}
          className={cn(inputClass, "w-full")}
          value={asText(value).slice(0, 5)}
          onChange={(event) => onChange(event.target.value || null)}
        />
      );
    case "date":
      return (
        <Input
          id={id}
          aria-label={name}
          type="date"
          disabled={disabled}
          className={cn(inputClass, "w-full")}
          value={asText(value)}
          onChange={(event) => onChange(event.target.value || null)}
        />
      );
    case "datetime":
      return (
        <Input
          id={id}
          aria-label={name}
          type="datetime-local"
          disabled={disabled}
          className={cn(inputClass, "w-full")}
          value={toLocalInput(value)}
          onChange={(event) => onChange(fromLocalInput(event.target.value))}
        />
      );
    default:
      return (
        <Input
          id={id}
          aria-label={name}
          disabled={disabled}
          className={cn(inputClass, "w-full")}
          value={asText(value)}
          onChange={(event) => onChange(event.target.value)}
        />
      );
  }
}

/**
 * A table the team scrolls and adds rows to, like the paper's.
 *
 * Rows are plain objects; the grid only edits them and hands the new list back. A
 * row can carry a child list (a run's semoule lines) which opens under it.
 */
export function ShiftGrid({
  columns,
  rows,
  onChange,
  options,
  disabled,
  addLabel,
  child,
  defaults,
  idPrefix,
  storageKey,
  keepOne,
  decorate,
  onCellFocus,
}: {
  columns: Column[];
  rows: GridRow[];
  onChange: (rows: GridRow[]) => void;
  options: OptionMap;
  disabled?: boolean;
  addLabel: string;
  child?: ChildDef;
  /** What a line added here starts with (the shift's lot); the team can type over it. */
  defaults?: Row;
  idPrefix: string;
  /** Where this grid's column widths are remembered on this device; omit to not remember. */
  storageKey?: string;
  /** The table never drops below one line: removing the only line clears it instead. */
  keepOne?: boolean;
  /** Marks a cell (the scan review's yellow doubts and red required values). */
  decorate?: (row: Row, key: string) => CellDecor | undefined;
  /** Called when a cell takes focus (the scan review shows where the value was read). */
  onCellFocus?: (row: Row, key: string) => void;
}) {
  const label = useLabel();
  const sizing = useColumnWidths(storageKey, columns);
  const reduceMotion = useReducedMotion();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const setCell = (index: number, key: string, value: unknown) => {
    // A cell can invalidate what the server derived from it (a new product means a new OF to resolve).
    const column = columns.find((c) => c.key === key);
    const cleared = Object.fromEntries((column?.resets ?? []).map((field) => [field, null]));
    const typedOver = (row: GridRow) => row._auto?.filter((auto) => auto !== key);
    onChange(
      rows.map((row, i) =>
        i === index
          ? { ...row, ...cleared, ...column?.fills?.(value, row, options), _fresh: false, _auto: typedOver(row), [key]: value }
          : row,
      ),
    );
  };
  const remove = (index: number) =>
    onChange(keepOne && rows.length === 1 ? [blankRow(child?.payloadKey, defaults)] : rows.filter((_, i) => i !== index));
  const add = () => onChange([...rows, blankRow(child?.payloadKey, defaults)]);
  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const span = columns.length + (child ? 2 : 1);
  // The remove and expand controls and the first column stay put while the rest scrolls,
  // so a wide row never loses the name of what it is about.
  const pin = "sticky z-[1]";
  const expandLeft = "left-9";
  const firstLeft = child ? "left-[4.5rem]" : "left-9";

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-md border border-border scrollbar-thin">
        <table
          className="min-w-full border-collapse text-sm"
          style={{ tableLayout: "fixed", width: sizing.total + CONTROL_WIDTH * (child ? 2 : 1) }}
        >
          <colgroup>
            <col style={{ width: CONTROL_WIDTH }} />
            {child && <col style={{ width: CONTROL_WIDTH }} />}
            {columns.map((column) => (
              <col key={column.key} style={{ width: sizing.widthOf(column) }} />
            ))}
          </colgroup>
          <thead>
            <tr className="bg-muted/70">
              <th className={cn("w-9 min-w-9 bg-muted left-0", pin)} />
              {child && <th className={cn("w-9 min-w-9 bg-muted", pin, expandLeft)} />}
              {columns.map((column, columnIndex) => (
                <th
                  key={column.key}
                  scope="col"
                  title={label(column.label)}
                  className={cn(
                    "relative overflow-hidden text-ellipsis whitespace-nowrap py-2 pl-1.5 pr-3 text-left text-xs font-medium text-muted-foreground",
                    columnIndex === 0 && cn("bg-muted border-r border-border/70", pin, firstLeft),
                  )}
                >
                  {label(column.label)}
                  {column.required && <span className="ml-0.5 text-destructive">*</span>}
                  <ResizeHandle
                    width={sizing.widthOf(column)}
                    onResize={(px) => sizing.setWidth(column, px)}
                    onReset={() => sizing.resetOne(column)}
                    label={label(T.resizeColumn)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={span} className="px-3 py-5 text-center text-xs text-muted-foreground">
                  {label(T.emptyRows)}
                </td>
              </tr>
            )}
            {rows.map((row, index) => {
              const kids = child ? ((row[child.payloadKey] as GridRow[] | undefined) ?? []) : [];
              const open = expanded.has(row._key);
              return (
                <Fragment key={row._key}>
                  <motion.tr
                    initial={row._fresh && !reduceMotion ? { opacity: 0, backgroundColor: "rgba(18, 59, 109, 0.09)" } : false}
                    animate={{ opacity: 1, backgroundColor: "rgba(18, 59, 109, 0)" }}
                    transition={{ duration: 0.4 }}
                    className="border-t border-border/70 align-middle"
                  >
                    <td className={cn("bg-background px-1 py-1 text-center left-0", pin)}>
                      {!disabled && !(keepOne && rows.length === 1 && isBlankRow(row)) && (
                        <button
                          type="button"
                          onClick={() => remove(index)}
                          aria-label={label(T.removeRow)}
                          title={label(T.removeRow)}
                          className="rounded p-1 text-muted-foreground transition-colors hover:bg-destructive-soft hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </td>
                    {child && (
                      <td className={cn("bg-background px-1 py-1 text-center", pin, expandLeft)}>
                        <button
                          type="button"
                          onClick={() => toggle(row._key)}
                          aria-expanded={open}
                          aria-label={label(T.expand)}
                          title={label(T.expand)}
                          className="inline-flex items-center gap-0.5 rounded p-1 text-xs text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
                          {kids.length > 0 && <span className="tabular-nums">{kids.length}</span>}
                        </button>
                      </td>
                    )}
                    {columns.map((column, columnIndex) => {
                      const decor = decorate?.(row, column.key);
                      return (
                      <td
                        key={column.key}
                        title={decor?.title}
                        onFocusCapture={onCellFocus ? () => onCellFocus(row, column.key) : undefined}
                        className={cn(
                          "px-1 py-1",
                          columnIndex === 0 && cn("bg-background border-r border-border/70", pin, firstLeft),
                          decor && DECOR_CLASS[decor.tone],
                        )}
                      >
                        <Cell
                          column={column}
                          value={row[column.key]}
                          row={row}
                          onChange={(value) => setCell(index, column.key, value)}
                          options={options}
                          disabled={disabled}
                          idPrefix={`${idPrefix}-${row._key}`}
                        />
                      </td>
                      );
                    })}
                  </motion.tr>
                  {child && open && (
                    <tr className="bg-muted/30">
                      <td />
                      <td colSpan={span - 1} className="px-2 py-3">
                        <p className="mb-2 text-xs font-medium text-muted-foreground">{label(child.title)}</p>
                        <ShiftGrid
                          columns={child.columns}
                          rows={kids}
                          onChange={(next) => setCell(index, child.payloadKey, next)}
                          options={options}
                          disabled={disabled}
                          addLabel={label(child.addLabel)}
                          idPrefix={`${idPrefix}-${row._key}-child`}
                          storageKey={storageKey ? `${storageKey}-child` : undefined}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-2">
        {!disabled ? (
          <button
            type="button"
            onClick={add}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Plus className="h-3.5 w-3.5" />
            {addLabel}
          </button>
        ) : (
          <span />
        )}
        {sizing.customised && (
          <button
            type="button"
            onClick={sizing.resetAll}
            className="rounded-md px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {label(T.resetColumns)}
          </button>
        )}
      </div>
    </div>
  );
}
