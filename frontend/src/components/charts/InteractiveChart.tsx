import {
  Children,
  Fragment,
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { ChartColumn, ChartLine, ChartScatter, Maximize2, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import {
  Area,
  Bar,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  XAxis,
  YAxis,
} from "recharts";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../ui/dialog";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";

/**
 * Drop-in replacement for Recharts' `ResponsiveContainer` that makes the chart
 * inside it explorable:
 *
 * - legend chips: click hides/shows a series, double-click shows only that one;
 * - zoom: drag across the plot, Ctrl + wheel, or the +/- buttons; double-click
 *   the plot (or the reset button) to see everything again;
 * - pan: Shift + wheel moves the zoomed window;
 * - expand: opens the same chart larger in a dialog;
 * - view: plain line/bar series can be redrawn as lines, bars or points.
 *
 * It reads the chart's own children (Line/Bar/Area/Scatter/Pie), so callers
 * keep writing ordinary Recharts markup — only the container changes.
 */

type SeriesKind = "line" | "bar" | "area" | "scatter";
type ViewMode = "original" | "line" | "bar" | "points";

interface SeriesInfo {
  id: string;
  label: string;
  color: string;
  /** How the chip draws its swatch, so it matches the mark on the plot. */
  swatch: "dot" | "line" | "dashed";
}

const NEUTRAL = "hsl(215 16% 60%)";
const EXPANDED_HEIGHT = 400;
const MIN_WINDOW = 2;

// Flattens arrays and fragments so series produced by `.map()` or wrapped in
// `<>…</>` are seen as direct children of the chart.
function flatten(children: ReactNode): ReactElement[] {
  const out: ReactElement[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    if (child.type === Fragment) out.push(...flatten((child.props as { children?: ReactNode }).children));
    else out.push(child);
  });
  return out;
}

function seriesKind(element: ReactElement): SeriesKind | null {
  if (element.type === Line) return "line";
  if (element.type === Bar) return "bar";
  if (element.type === Area) return "area";
  if (element.type === Scatter) return "scatter";
  return null;
}

type AnyProps = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function usableColor(value: unknown): string | null {
  return typeof value === "string" && value !== "none" && !value.startsWith("url(") ? value : null;
}

function seriesId(props: AnyProps, index: number): string {
  if (typeof props.dataKey === "string" || typeof props.dataKey === "number") return String(props.dataKey);
  if (props.name != null) return String(props.name);
  return `series-${index}`;
}

function seriesColor(element: ReactElement, kind: SeriesKind): string {
  const props = element.props as AnyProps;
  const firstCell = flatten(props.children).find((child) => child.type === Cell);
  const cellFill = firstCell ? usableColor((firstCell.props as AnyProps).fill) : null;
  const ordered =
    kind === "line" ? [props.stroke, props.fill] : kind === "area" ? [props.stroke, props.fill] : [props.fill, props.stroke];
  for (const candidate of ordered) {
    const color = usableColor(candidate);
    if (color) return color;
  }
  return cellFill ?? NEUTRAL;
}

export interface InteractiveChartProps {
  /** Same meaning as on ResponsiveContainer; a number is the plot height. */
  height?: number | string;
  width?: number | string;
  className?: string;
  /** Turn the view switcher off for charts whose shape carries meaning. */
  allowViewSwitch?: boolean;
  /** Force the clickable series chips on/off (default: on when there are 2+ series). */
  legend?: boolean;
  /** Internal: the enlarged copy starts from the small chart's state and has no expand button. */
  expandedFrom?: { hidden: Set<string>; view: ViewMode; title: string; description: string };
  children: ReactElement;
}

export function InteractiveChart({ height = "100%", width = "100%", className, allowViewSwitch = true, legend, expandedFrom, children }: InteractiveChartProps) {
  const { t } = useI18n();
  const chart = children;
  const chartProps = chart.props as AnyProps;
  const data: AnyProps[] = Array.isArray(chartProps.data) ? chartProps.data : [];
  const parts = useMemo(() => flatten(chartProps.children), [chartProps.children]);

  // ---- what kind of chart is this -------------------------------------------------
  const xAxis = parts.find((part) => part.type === XAxis);
  const yAxis = parts.find((part) => part.type === YAxis);
  const xAxisProps = (xAxis?.props ?? {}) as AnyProps;
  const yAxisProps = (yAxis?.props ?? {}) as AnyProps;
  const xKey: string | undefined = typeof xAxisProps.dataKey === "string" ? xAxisProps.dataKey : undefined;
  const isVertical = chartProps.layout === "vertical";
  const hasPie = parts.some((part) => part.type === Pie);
  const hasScatter = parts.some((part) => part.type === Scatter);
  const zoomable = !isVertical && !hasPie && !hasScatter && xAxisProps.type !== "number" && data.length > MIN_WINDOW;

  const series = useMemo(() => {
    const list: (SeriesInfo & { kind: SeriesKind })[] = [];
    parts.forEach((part, index) => {
      const kind = seriesKind(part);
      if (!kind) return;
      const props = part.props as AnyProps;
      const id = seriesId(props, index);
      const swatch = kind === "line" || kind === "area" ? (props.strokeDasharray ? "dashed" : "line") : "dot";
      list.push({ id, kind, label: String(props.name ?? id), color: seriesColor(part, kind), swatch });
    });
    return list;
  }, [parts]);

  // Pie slices behave like series: one chip per slice of the first pie.
  const pieElement = parts.find((part) => part.type === Pie);
  const pieSlices = useMemo<SeriesInfo[]>(() => {
    if (!pieElement) return [];
    const props = pieElement.props as AnyProps;
    const rows: AnyProps[] = Array.isArray(props.data) ? props.data : [];
    const nameKey = typeof props.nameKey === "string" ? props.nameKey : "name";
    const cells = flatten(props.children).filter((child) => child.type === Cell);
    return rows.map((row, index) => {
      const label = String(row[nameKey] ?? index);
      const color = usableColor((cells[index]?.props as AnyProps | undefined)?.fill) ?? usableColor(row.fill) ?? usableColor(props.fill) ?? NEUTRAL;
      return { id: `${index}:${label}`, label, color, swatch: "dot" as const };
    });
  }, [pieElement]);

  const chips: SeriesInfo[] = hasPie ? pieSlices : series;
  // Pies here usually carry their own richer legend (counts, translated
  // labels) outside the chart, so they only get chips when they asked Recharts
  // for a legend.
  const legendElement = parts.find((part) => part.type === Legend);
  const hasLegend = legendElement !== undefined;
  // Keep the chart's own legend wording (e.g. a formatter that translates keys).
  const legendFormatter = (legendElement?.props as AnyProps | undefined)?.formatter;
  const chipLabel = (chip: SeriesInfo, index: number): ReactNode =>
    typeof legendFormatter === "function" ? legendFormatter(chip.label, { value: chip.label, color: chip.color }, index) : chip.label;
  const showChips = (legend ?? (hasPie ? hasLegend : true)) && chips.length > 1;

  const switchable =
    allowViewSwitch &&
    zoomable &&
    series.length > 0 &&
    series.every((s) => s.kind === "line" || s.kind === "bar") &&
    parts.every((part) => {
      const kind = seriesKind(part);
      if (!kind) return true;
      const props = part.props as AnyProps;
      // Per-bar colours or custom marks mean the shape itself carries
      // information that a redraw would lose.
      return flatten(props.children).length === 0 && typeof props.dot !== "function" && typeof props.shape !== "function";
    });

  // ---- state ----------------------------------------------------------------------
  const [hidden, setHidden] = useState<Set<string>>(() => new Set(expandedFrom?.hidden ?? []));
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState<ViewMode>(expandedFrom?.view ?? "original");
  const [expanded, setExpanded] = useState<{ title: string; description: string } | null>(null);

  const dataKeyOf = useCallback((index: number) => (xKey ? data[index]?.[xKey] : index), [data, xKey]);
  const dataSignature = `${data.length}|${String(dataKeyOf(0))}|${String(dataKeyOf(data.length - 1))}`;
  const [range, setRange] = useState<{ start: number; end: number; signature: string } | null>(null);
  // A new dataset (other period, other filter) starts un-zoomed.
  const activeRange = range && range.signature === dataSignature ? range : null;
  const start = activeRange?.start ?? 0;
  const end = activeRange?.end ?? Math.max(0, data.length - 1);
  const isZoomed = activeRange !== null;

  // Hidden series that no longer exist should not linger.
  useEffect(() => {
    setHidden((current) => {
      const ids = new Set(chips.map((chip) => chip.id));
      const next = new Set([...current].filter((id) => ids.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [chips]);

  const applyRange = useCallback(
    (nextStart: number, nextEnd: number) => {
      const last = data.length - 1;
      let s = Math.max(0, Math.min(nextStart, last));
      let e = Math.max(0, Math.min(nextEnd, last));
      if (e < s) [s, e] = [e, s];
      if (e - s + 1 < MIN_WINDOW) {
        e = Math.min(last, s + MIN_WINDOW - 1);
        s = Math.max(0, e - MIN_WINDOW + 1);
      }
      setRange(s === 0 && e === last ? null : { start: s, end: e, signature: dataSignature });
    },
    [data.length, dataSignature],
  );

  const zoomBy = useCallback(
    (factor: number, anchor?: number) => {
      const size = end - start + 1;
      const nextSize = Math.max(MIN_WINDOW, Math.min(data.length, Math.round(size * factor) + (factor > 1 ? 1 : 0)));
      if (nextSize === size) return;
      const pivot = anchor !== undefined && anchor >= start && anchor <= end ? anchor : (start + end) / 2;
      const nextStart = Math.round(pivot - ((pivot - start) * nextSize) / size);
      const clampedStart = Math.max(0, Math.min(nextStart, data.length - nextSize));
      applyRange(clampedStart, clampedStart + nextSize - 1);
    },
    [applyRange, data.length, end, start],
  );

  const panBy = useCallback(
    (direction: number) => {
      const size = end - start + 1;
      if (size >= data.length) return;
      const step = Math.max(1, Math.round(size * 0.15)) * direction;
      const nextStart = Math.max(0, Math.min(start + step, data.length - size));
      applyRange(nextStart, nextStart + size - 1);
    },
    [applyRange, data.length, end, start],
  );

  // ---- drag-to-zoom + wheel -------------------------------------------------------
  const indexOfLabel = useCallback(
    (label: unknown, fallbackIndex: unknown): number | null => {
      if (xKey && label !== undefined) {
        const found = data.findIndex((row) => row[xKey] === label);
        if (found >= 0) return found;
      }
      const numeric = Number(fallbackIndex);
      return Number.isInteger(numeric) && numeric >= 0 && numeric < data.length ? numeric : null;
    },
    [data, xKey],
  );

  const [selection, setSelectionState] = useState<{ from: number; to: number } | null>(null);
  const selectionRef = useRef<{ from: number; to: number } | null>(null);
  const setSelection = (next: { from: number; to: number } | null) => {
    selectionRef.current = next;
    setSelectionState(next);
  };
  const hoverIndex = useRef<number | null>(null);

  const plotRef = useRef<HTMLDivElement>(null);
  const wheelState = useRef({ zoomBy, panBy, zoomable });
  wheelState.current = { zoomBy, panBy, zoomable };
  useEffect(() => {
    const node = plotRef.current;
    if (!node) return;
    // Native listener: React's onWheel is passive, so it cannot stop the page
    // from scrolling while the chart zooms.
    const onWheel = (event: WheelEvent) => {
      const state = wheelState.current;
      if (!state.zoomable) return;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        state.zoomBy(event.deltaY < 0 ? 0.8 : 1.25, hoverIndex.current ?? undefined);
      } else if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        event.preventDefault();
        const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
        state.panBy(delta > 0 ? 1 : -1);
      }
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, []);

  // ---- chip interactions ----------------------------------------------------------
  const toggle = (id: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const isolate = (id: string) =>
    setHidden((current) => {
      const onlyThis = chips.every((chip) => (chip.id === id ? !current.has(chip.id) : current.has(chip.id)));
      return onlyThis ? new Set() : new Set(chips.filter((chip) => chip.id !== id).map((chip) => chip.id));
    });

  // ---- rebuild the chart ----------------------------------------------------------
  const effectiveView: ViewMode = switchable ? view : "original";
  const dim = (id: string) => hovered !== null && hovered !== id;

  const rebuilt: ReactNode[] = [];
  let seriesIndex = 0;
  parts.forEach((part, index) => {
    const key = part.key ?? `part-${index}`;
    if (part.type === Legend && showChips) return; // the chips replace it
    const kind = seriesKind(part);
    if (kind) {
      const info = series[seriesIndex++];
      const props = part.props as AnyProps;
      const isHidden = hidden.has(info.id);
      const faded = dim(info.id);
      if (effectiveView === "original") {
        rebuilt.push(
          cloneElement(part as ReactElement<AnyProps>, {
            key,
            hide: isHidden || props.hide,
            ...(faded
              ? kind === "line"
                ? { strokeOpacity: 0.2 }
                : kind === "area"
                  ? { strokeOpacity: 0.2, fillOpacity: 0.05 }
                  : { fillOpacity: 0.2 }
              : {}),
          }),
        );
        return;
      }
      const shared = {
        key,
        dataKey: props.dataKey,
        name: props.name ?? info.label,
        yAxisId: props.yAxisId,
        xAxisId: props.xAxisId,
        unit: props.unit,
        hide: isHidden || props.hide,
        isAnimationActive: false,
      };
      if (effectiveView === "bar") {
        rebuilt.push(<Bar {...shared} fill={info.color} fillOpacity={faded ? 0.2 : 1} radius={[4, 4, 0, 0]} />);
      } else if (effectiveView === "line") {
        rebuilt.push(
          <Line {...shared} type="monotone" stroke={info.color} strokeOpacity={faded ? 0.2 : 1} strokeWidth={2} dot={{ r: 3 }} connectNulls />,
        );
      } else {
        rebuilt.push(
          <Line
            {...shared}
            stroke="transparent"
            strokeWidth={0}
            dot={{ r: 4, fill: info.color, stroke: info.color, fillOpacity: faded ? 0.2 : 1, strokeOpacity: faded ? 0.2 : 1 }}
            activeDot={{ r: 6, fill: info.color }}
            legendType="circle"
          />,
        );
      }
      return;
    }
    if (part.type === Pie && part === pieElement && pieSlices.length > 0) {
      const props = part.props as AnyProps;
      const rows: AnyProps[] = Array.isArray(props.data) ? props.data : [];
      const pieChildren = flatten(props.children);
      const cells = pieChildren.filter((child) => child.type === Cell);
      const others = pieChildren.filter((child) => child.type !== Cell);
      const keep = rows.map((_, rowIndex) => !hidden.has(pieSlices[rowIndex].id));
      rebuilt.push(
        cloneElement(
          part as ReactElement<AnyProps>,
          { key, data: rows.filter((_, rowIndex) => keep[rowIndex]) },
          ...cells.filter((_, cellIndex) => keep[cellIndex]),
          ...others,
        ),
      );
      return;
    }
    rebuilt.push(cloneElement(part, { key }));
  });

  if (selection) {
    const from = Math.min(selection.from, selection.to);
    const to = Math.max(selection.from, selection.to);
    rebuilt.push(
      <ReferenceArea
        key="__zoom-selection"
        x1={xKey ? data[from]?.[xKey] : from}
        x2={xKey ? data[to]?.[xKey] : to}
        xAxisId={xAxisProps.xAxisId}
        yAxisId={yAxisProps.yAxisId}
        fill="#123B6D"
        fillOpacity={0.08}
        stroke="#123B6D"
        strokeOpacity={0.3}
        ifOverflow="hidden"
      />,
    );
  }

  const handlers = zoomable
    ? {
        onMouseDown: (state: AnyProps, event: unknown) => {
          chartProps.onMouseDown?.(state, event);
          const index = indexOfLabel(state?.activeLabel, state?.activeTooltipIndex);
          if (index !== null) setSelection({ from: index, to: index });
        },
        onMouseMove: (state: AnyProps, event: unknown) => {
          chartProps.onMouseMove?.(state, event);
          const index = indexOfLabel(state?.activeLabel, state?.activeTooltipIndex);
          hoverIndex.current = index;
          const current = selectionRef.current;
          if (index !== null && current && current.to !== index) setSelection({ ...current, to: index });
        },
        onMouseUp: (state: AnyProps, event: unknown) => {
          chartProps.onMouseUp?.(state, event);
          const current = selectionRef.current;
          setSelection(null);
          if (current && current.from !== current.to) applyRange(Math.min(current.from, current.to), Math.max(current.from, current.to));
        },
        onMouseLeave: (state: AnyProps, event: unknown) => {
          chartProps.onMouseLeave?.(state, event);
          hoverIndex.current = null;
          if (selectionRef.current) setSelection(null);
        },
      }
    : {};

  const ChartType = effectiveView === "original" ? chart.type : ComposedChart;
  const rendered = (
    <ChartType {...chartProps} {...handlers} key={effectiveView}>
      {rebuilt}
    </ChartType>
  );

  // ---- layout ---------------------------------------------------------------------
  const numericHeight = typeof height === "number" ? height : null;
  const canExpand = !expandedFrom;
  const anyHidden = hidden.size > 0;

  return (
    <div className={cn("flex min-w-0 flex-col", numericHeight === null && "h-full", className)} style={{ width }}>
      {(zoomable || canExpand) && (
        <div className="mb-2 flex items-center justify-end">
          {(
            <div className="flex items-center gap-0.5 rounded-md border border-border bg-background p-0.5">
              {switchable && (
                <>
                  {(
                    [
                      ["line", ChartLine, "chart.view.line"],
                      ["bar", ChartColumn, "chart.view.bar"],
                      ["points", ChartScatter, "chart.view.points"],
                    ] as const
                  ).map(([mode, Icon, label]) => {
                    const active =
                      effectiveView === mode ||
                      (effectiveView === "original" && series.every((s) => s.kind === (mode === "points" ? "scatter" : mode)));
                    return (
                      <ToolbarButton
                        key={mode}
                        label={t(label)}
                        active={active}
                        onClick={() => setView(active ? "original" : mode)}
                      >
                        <Icon className="h-3.5 w-3.5" />
                      </ToolbarButton>
                    );
                  })}
                  <span className="mx-0.5 h-4 w-px bg-border" />
                </>
              )}
              {zoomable && (
                <>
                  <ToolbarButton label={`${t("chart.zoom.in")} — ${t("chart.zoom.hint")}`} onClick={() => zoomBy(0.66)} disabled={end - start + 1 <= MIN_WINDOW}>
                    <ZoomIn className="h-3.5 w-3.5" />
                  </ToolbarButton>
                  <ToolbarButton label={t("chart.zoom.out")} onClick={() => zoomBy(1.5)} disabled={!isZoomed}>
                    <ZoomOut className="h-3.5 w-3.5" />
                  </ToolbarButton>
                  <ToolbarButton label={t("chart.zoom.reset")} onClick={() => setRange(null)} disabled={!isZoomed}>
                    <RotateCcw className="h-3.5 w-3.5" />
                  </ToolbarButton>
                </>
              )}
              {canExpand && (
                <>
                  {zoomable && <span className="mx-0.5 h-4 w-px bg-border" />}
                  <ToolbarButton label={t("chart.expand")} onClick={() => setExpanded(headingFor(plotRef.current))}>
                    <Maximize2 className="h-3.5 w-3.5" />
                  </ToolbarButton>
                </>
              )}
            </div>
          )}
        </div>
      )}
      <div
        ref={plotRef}
        className={cn("min-h-0 select-none [&_*:focus]:outline-none",numericHeight === null && "flex-1", zoomable && "cursor-crosshair")}
        style={numericHeight !== null ? { height: numericHeight } : undefined}
        onDoubleClick={() => zoomable && setRange(null)}
      >
        <ResponsiveContainer width="100%" height="100%">
          {rendered}
        </ResponsiveContainer>
      </div>
      {showChips && (
        <div className="mt-2 flex min-w-0 flex-wrap items-center justify-center gap-1.5">
            {chips.map((chip, chipIndex) => {
                const off = hidden.has(chip.id);
                return (
                  <button
                    key={chip.id}
                    type="button"
                    onClick={() => toggle(chip.id)}
                    onDoubleClick={() => isolate(chip.id)}
                    onMouseEnter={() => !off && setHovered(chip.id)}
                    onMouseLeave={() => setHovered(null)}
                    title={t("chart.legend.hint")}
                    aria-pressed={!off}
                    className={cn(
                      "inline-flex max-w-[14rem] select-none items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors",
                      off
                        ? "border-dashed border-border text-muted-foreground/70 line-through"
                        : "border-border bg-background text-foreground hover:bg-muted",
                    )}
                  >
                    {chip.swatch === "dot" ? (
                      <span
                        className="inline-block h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: off ? "transparent" : chip.color, boxShadow: `inset 0 0 0 1.5px ${chip.color}` }}
                      />
                    ) : (
                      <svg width="18" height="8" aria-hidden="true" className="shrink-0" style={{ opacity: off ? 0.4 : 1 }}>
                        <line x1="0" y1="4" x2="18" y2="4" stroke={chip.color} strokeWidth="2.4" strokeDasharray={chip.swatch === "dashed" ? "4 3" : undefined} />
                      </svg>
                    )}
                    <span className="truncate">{chipLabel(chip, chipIndex)}</span>
                  </button>
                );
              })}
            {anyHidden && (
              <button
                type="button"
                onClick={() => setHidden(new Set())}
                className="px-1 text-xs font-medium text-primary hover:underline"
              >
                {t("chart.legend.showAll")}
              </button>
            )}
          </div>
      )}
      {canExpand && (
        <Dialog open={expanded !== null} onOpenChange={(open) => !open && setExpanded(null)}>
          <DialogContent className="max-w-5xl">
            <DialogHeader className="pr-8">
              <DialogTitle>{expanded?.title || t("chart.expand")}</DialogTitle>
              {expanded?.description ? <DialogDescription>{expanded.description}</DialogDescription> : null}
            </DialogHeader>
            {expanded && (
              <InteractiveChart
                height={EXPANDED_HEIGHT}
                allowViewSwitch={allowViewSwitch}
                legend={legend}
                expandedFrom={{ hidden, view, ...expanded }}
              >
                {children}
              </InteractiveChart>
            )}
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

// The chart doesn't know its card's title; borrow the nearest heading above
// it so the enlarged view is labelled like the card it came from.
function headingFor(node: HTMLElement | null): { title: string; description: string } {
  let current = node?.parentElement ?? null;
  while (current && current !== document.body) {
    const heading = current.querySelector("h1, h2, h3, h4");
    if (heading && !node?.contains(heading)) {
      const description = heading.parentElement?.querySelector("p");
      return { title: heading.textContent?.trim() ?? "", description: description?.textContent?.trim() ?? "" };
    }
    current = current.parentElement;
  }
  return { title: "", description: "" };
}

function ToolbarButton({
  label,
  onClick,
  disabled,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40",
        active && "bg-muted text-foreground",
      )}
    >
      {children}
    </button>
  );
}
