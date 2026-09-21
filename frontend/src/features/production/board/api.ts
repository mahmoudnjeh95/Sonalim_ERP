import { apiFetch } from "../../../lib/api";
import type { ProductionStage } from "../../maintenance/api";

// --- The live board ---------------------------------------------------------

/** How an open OF is shown on its line. A line with no open OF is not shown. */
export type LineState = "running" | "maintenance" | "down" | "suspended";
export type MachineStatus = "operational" | "maintenance" | "down";
/** Declared on the machine, in Maintenance. */
export type Stage = ProductionStage;

export interface BoardMachine {
  id: string;
  code: string;
  name: string;
  status: MachineStatus;
  /** null for a machine registered with no stage. */
  stage: Stage | null;
}

export interface RosterEntry {
  shift: string;
  team: string;
  /** null until the plant has set the shift's hours. */
  start_time: string | null;
  end_time: string | null;
  is_current: boolean;
}

export interface BoardOf {
  of_id: string;
  reference: string;
  status: "ongoing" | "suspended";
  product_type: "PL" | "PC" | null;
  product_name: string | null;
  start_date: string | null;
  state: LineState;
}

export interface BoardLine {
  work_center_id: string;
  code: string;
  name: string;
  is_blocked: boolean;
  blocked_reason: string | null;
  ofs: BoardOf[];
  /** Every machine declared on the line: in stage order, the ones with no stage last. */
  machines: BoardMachine[];
  roster: RosterEntry[];
}

export interface ShiftWindowRow {
  shift: string;
  start_time: string;
  end_time: string;
  /** How long the shift runs, across midnight if need be. Read from the settings; never sent back. */
  length_minutes?: number;
}

export interface BoardLines {
  at: string;
  current_shift: ShiftWindowRow | null;
  shift_windows: ShiftWindowRow[];
  lines: BoardLine[];
}

export function getBoardLines(token: string, at: string) {
  return apiFetch<BoardLines>(`/production/dashboard/lines?at=${encodeURIComponent(at)}`, { token });
}

// --- One day ----------------------------------------------------------------

export type Direction = "up" | "down" | "flat" | null;

export interface DayTotals {
  semolina_poured: number;
  finished_product: number;
  yield_pct: number | null;
  downtime_minutes: number;
  report_count: number;
}

export interface DayOf {
  of_id: string;
  reference: string | null;
  product_type: "PL" | "PC" | null;
  work_center_id: string | null;
  semolina_poured: number;
  regrind_input: number;
  finished_product: number;
  yield_pct: number | null;
  production_minutes: number;
  downtime_minutes: number;
  waste_kg: number;
  packets_counted: number | null;
  output_by_shift: { shift: string | null; team: string | null; finished_product: number }[];
  semolina_by_product: { product_id: string; name: string | null; unit: string | null; quantity: number }[];
  stops: { motif: string | null; team: string | null; minutes: number }[];
}

export interface WasteRow {
  category: string;
  team: string | null;
  work_center_id: string | null;
  value: number;
}

export interface StopRow {
  motif: string | null;
  team: string | null;
  work_center_id: string | null;
  value: number;
}

// --- Releasing packed goods ---------------------------------------------------

export const RELEASE_STOCK_PERMISSION = "production.release_stock";

export interface ReleaseItem {
  product_id: string;
  product_name: string;
  uom_id: string;
  /** Pieces in a carton; null when the product has no carton tier (a sac, or loose packets). */
  packets_per_carton: number | null;
  packaging_format: "packet" | "carton" | "sac" | null;
  /** All four quantities are in the product's own unit. `releasable` is what the line store can actually give now. */
  packed: number;
  released: number;
  remaining: number;
  releasable: number;
  /** null when the product has no default storage location: it cannot be released until one is set. */
  destination: { id: string; name: string | null } | null;
}

export interface StockReleaseList {
  /** The day whose packing reports are listed (YYYY-MM-DD), and today's date. */
  day: string;
  today: string;
  /** null when the production settings name no single line store. */
  line_store: { id: string; name: string | null } | null;
  items: ReleaseItem[];
}

/** Without a day the server opens on yesterday, or on today once yesterday has nothing left to release. */
export function getStockRelease(token: string, day?: string | null) {
  return apiFetch<StockReleaseList>(`/production/stock-release${day ? `?day=${day}` : ""}`, { token });
}

export function releaseStock(token: string, day: string, items: { product_id: string; quantity: number }[]) {
  return apiFetch<{ reference: string; day: string; released: { product_id: string; quantity: number; to_location_id: string }[] }>(
    "/production/stock-release",
    { method: "POST", token, body: { day, items } },
  );
}

// --- The shift running now ---------------------------------------------------

/** Where the current shift's report stands. Only `validated` is a result; the rest is work in progress. */
export type LiveStatus = "open" | "submitted" | "returned" | "validated";

export interface LiveOf {
  of_id: string;
  reference: string | null;
  semolina_poured: number;
  finished_product: number;
  yield_pct: number | null;
  production_minutes: number;
  downtime_minutes: number;
  waste_kg: number;
  packets_counted: number | null;
  stops: { motif: string | null; minutes: number }[];
}

export interface LiveLine {
  work_center_id: string;
  report: { id: string; status: LiveStatus; team: string | null };
  /** Empty for a shift sent back to its team. */
  ofs: LiveOf[];
  /** Machines whose stop has begun and not ended yet. */
  ongoing_stops: { equipment_id: string | null; since: string; motif: string | null }[];
}

export interface BoardLive {
  at: string;
  /** null when the plant has configured no shift for this time. */
  shift: { shift: string; start_time: string; end_time: string; report_date: string } | null;
  unit: string | null;
  lines: LiveLine[];
}

export function getBoardLive(token: string, date: string, at: string) {
  return apiFetch<BoardLive>(`/production/dashboard/live?date=${encodeURIComponent(date)}&at=${encodeURIComponent(at)}`, { token });
}

export interface BoardDay {
  date: string;
  previous_date: string;
  unit: string | null;
  awaiting_validation: number;
  totals: DayTotals;
  previous_totals: DayTotals | null;
  directions: {
    semolina_poured: Direction;
    finished_product: Direction;
    yield_pct: Direction;
    downtime_minutes: Direction;
  };
  ofs: DayOf[];
  waste: WasteRow[];
  stops: StopRow[];
}

export function getBoardDay(token: string, date: string) {
  return apiFetch<BoardDay>(`/production/dashboard/day?date=${encodeURIComponent(date)}`, { token });
}

// --- Trend ------------------------------------------------------------------

export type Granularity = "shift" | "day" | "week" | "month";

export interface TrendPoint {
  key: string;
  /** null when nobody reported: a missing day is not a day that produced nothing. */
  semolina_poured: number | null;
  finished_product: number | null;
}

export interface BoardTrend {
  granularity: Granularity;
  unit: string | null;
  current: { from: string; to: string; points: TrendPoint[] };
  previous: { from: string; to: string; points: TrendPoint[] };
}

export function getBoardTrend(token: string, params: { date_from: string; date_to: string; granularity: Granularity }) {
  const query = new URLSearchParams(params);
  return apiFetch<BoardTrend>(`/production/dashboard/trend?${query.toString()}`, { token });
}

// --- Configuration ----------------------------------------------------------

export type StoreRole = "line" | "final";

export interface DashboardSettings {
  shift_windows: ShiftWindowRow[];
  roster: { work_center_id: string; shift: string; team: string }[];
  store_roles: { location_id: string; role: StoreRole }[];
}

export const MANAGE_DASHBOARD_SETTINGS_PERMISSION = "production.manage_dashboard_settings";

export const DASHBOARD_SETTINGS_QUERY_KEY = ["production", "dashboard", "settings"] as const;

export function getDashboardSettings(token: string) {
  return apiFetch<DashboardSettings>("/production/dashboard/settings", { token });
}

function replaceSection<T>(token: string, section: string, items: T[]) {
  return apiFetch<T[]>(`/production/dashboard/settings/${section}`, { method: "PUT", token, body: { items } });
}

export const replaceShiftWindows = (token: string, items: DashboardSettings["shift_windows"]) =>
  replaceSection(token, "shift-windows", items);
export const replaceRoster = (token: string, items: DashboardSettings["roster"]) => replaceSection(token, "roster", items);
export const replaceStoreRoles = (token: string, items: DashboardSettings["store_roles"]) =>
  replaceSection(token, "store-roles", items);
