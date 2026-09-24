import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { listEquipment } from "../../maintenance/api";
import { listLocations, listProducts } from "../../warehouse/api";
import { listPartners } from "../../partners/api";
import { listClassifications, listMolds, listWorkCenters, listWorkOrders, type PackagingKind } from "../api";
import { DASHBOARD_SETTINGS_QUERY_KEY, getDashboardSettings } from "../board/api";
import { DOWNTIME_CLASSIFICATIONS, DOWNTIME_MOTIFS, DOWNTIME_TYPES } from "../DowntimeMotifSelect";
import { useWasteTypes } from "../wasteTypes";
import type { Option, OptionMap } from "./ShiftGrid";
import type { Row, SectionKey, ShiftReport } from "./shiftApi";
import { listShiftReports } from "./shiftApi";
import { packingTypeLabel } from "./packingType";
import { useLabel } from "./shiftText";

/**
 * Everything the shift grids' selects and the header need, loaded once and turned into
 * option lists. Shared by the team's entry screen and the validator's review, so both
 * show a lot, a machine or a work order under the same name.
 */
export function useShiftReferenceData(enabled: boolean) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const label = useLabel();
  const waste = useWasteTypes();

  const workCenters = useQuery({ queryKey: ["production", "shift", "work-centers"], queryFn: () => listWorkCenters(token), enabled });
  const settings = useQuery({ queryKey: DASHBOARD_SETTINGS_QUERY_KEY, queryFn: () => getDashboardSettings(token), enabled });
  const orders = useQuery({ queryKey: ["production", "shift", "orders"], queryFn: () => listWorkOrders(token), enabled });
  const products = useQuery({ queryKey: ["production", "shift", "products"], queryFn: () => listProducts(token), enabled });
  const classifications = useQuery({ queryKey: ["production", "shift", "classifications"], queryFn: () => listClassifications(token), enabled, retry: false });
  const locations = useQuery({ queryKey: ["production", "shift", "locations"], queryFn: () => listLocations(token), enabled });
  const molds = useQuery({ queryKey: ["production", "shift", "molds"], queryFn: () => listMolds(token), enabled });
  const equipment = useQuery({ queryKey: ["production", "shift", "equipment"], queryFn: () => listEquipment(token), enabled });
  const shiftReports = useQuery({ queryKey: ["production", "shift", "all-reports"], queryFn: () => listShiftReports(token), enabled });
  const partners = useQuery({ queryKey: ["production", "shift", "partners"], queryFn: () => listPartners(token), enabled });

  // Filter archived equipment and build report count map
  const activeEquipment = useMemo(
    () => (equipment.data ?? []).filter((e) => !e.archived_at).sort((a, b) => a.name.localeCompare(b.name)),
    [equipment.data],
  );

  const reportCountByLineDate = useMemo(() => {
    const map = new Map<string, number>();
    for (const report of shiftReports.data ?? []) {
      const key = `${report.report_date}|${report.work_center_id}`;
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return map;
  }, [shiftReports.data]);

  /** The option lists for one shift: the runs and packing rows it holds are choices for its waste and stop rows. */
  const buildOptions = useCallback(
    (shift: ShiftReport | undefined, workCenterId: string): OptionMap => {
      const productList = products.data ?? [];
      const productName = new Map(productList.map((p) => [p.id, p.name]));
      const productType = new Map(productList.map((p) => [p.id, p.product_type as string]));
      const all = orders.data ?? [];
      const orderById = new Map(all.map((o) => [o.id, o]));
      const rowsOf = (key: SectionKey, part: string) => {
        const payload = shift?.sections.find((s) => s.key === key)?.payload;
        return (Array.isArray(payload?.[part]) ? (payload![part] as Row[]) : []).filter((r) => typeof r.id === "string");
      };
      const time = (value: unknown) => (typeof value === "string" ? value.slice(0, 5) : "");
      const list = (source: readonly string[], prefix: string): Option[] =>
        source.map((value) => ({ value, label: t(`production.downtime.${prefix}.${value}` as TranslationKey) }));

      // Only orders still running are offered (never a regrind order); one a saved row already holds stays, so its name shows.
      const savedOrders = new Set([...rowsOf("runs", "runs"), ...rowsOf("packing", "rows")].map((r) => String(r.of_id)));
      const orderOption = (o: (typeof all)[number]): Option => ({
        value: o.id,
        label: o.product_id && productName.get(o.product_id) ? `${o.reference} – ${productName.get(o.product_id)}` : o.reference,
      });
      const pickable = all.filter((o) => (o.status === "ongoing" && !o.is_regrind) || savedOrders.has(o.id));

      // Products for the "item lost" and regrind selects: finished goods and raw materials only. If the
      // classifications cannot be read (no permission), nothing is filtered rather than emptying the list.
      const classOf = new Map((classifications.data ?? []).map((c) => [c.product_id, c]));
      const asOption = (p: (typeof productList)[number]): Option => ({ value: p.id, label: p.name });
      const productsOrMp = classifications.data
        ? productList.filter((p) => ["finished_good", "raw_material"].includes(classOf.get(p.id)?.category ?? "")).map(asOption)
        : productList.map(asOption);
      const itemsOfKind = (kind: PackagingKind): Option[] =>
        productList.filter((p) => classOf.get(p.id)?.packaging_kind === kind).map(asOption);
      // Products of a packing row: finished goods only (every product while classifications cannot be read).
      const finishedProducts = classifications.data
        ? productList.filter((p) => classOf.get(p.id)?.category === "finished_good").map(asOption)
        : productList.map(asOption);
      // Only orders that have a production row on this shift can be the OF of a lot.
      const runOrderIds = new Set(rowsOf("runs", "runs").map((r) => String(r.of_id)));
      // Products already packed this shift -- what a "Produit" packing-waste line may name.
      const packedProductIds = new Set(rowsOf("packing", "rows").map((r) => String(r.product_id)).filter(Boolean));
      const packedProducts = [...packedProductIds].map((id) => ({ value: id, label: productName.get(id) ?? id }));

      // Molds follow the type (PL or PC) of the work orders: a run's own row, or the shift's runs for a wash.
      const typeOfOrder = new Map(all.map((o) => [o.id, o.product_type ?? productType.get(o.product_id ?? "") ?? ""]));
      const runTypes = new Set(rowsOf("runs", "runs").map((r) => typeOfOrder.get(String(r.of_id)) ?? "").filter(Boolean));
      const moldList = molds.data ?? [];
      const moldOption = (m: (typeof moldList)[number]): Option => ({ value: m.id, label: `${m.code} – ${m.name}` });

      const runLabel = (r: Row) => {
        const order = orderById.get(String(r.of_id));
        const name = (order?.product_id && productName.get(order.product_id)) || order?.reference || "";
        return [name, time(r.start_time)].filter(Boolean).join(" · ") || String(r.id).slice(-6);
      };

      return {
        orders: pickable.map(orderOption),
        products: productList.map(asOption),
        productsOrMp,
        finishedProducts,
        shiftOrders: all.filter((o) => runOrderIds.has(o.id)).map(orderOption),
        packingTypes: productList
          .map((p) => ({ value: p.id, label: packingTypeLabel(p.net_weight_grams, classOf.get(p.id)?.packaging_format) }))
          .filter((option) => option.label),
        itemsFilm: itemsOfKind("film"),
        itemsCarton: itemsOfKind("carton"),
        itemsBobine: itemsOfKind("bobine"),
        itemsScotch: itemsOfKind("scotch"),
        itemsRuban: itemsOfKind("ruban"),
        packedProducts,
        locations: (locations.data ?? []).map((l) => ({ value: l.id, label: l.name })),
        molds: moldList.map(moldOption),
        moldsForShift: moldList.filter((m) => runTypes.size === 0 || runTypes.has(m.type)).map(moldOption),
        orderTypes: [...typeOfOrder].map(([value, type]) => ({ value, label: type })),
        moldTypes: moldList.map((m) => ({ value: m.id, label: m.type })),
        partners: (partners.data ?? []).map((p) => ({ value: p.id, label: p.name })),
        equipment: (equipment.data ?? [])
          .filter((e) => !workCenterId || e.work_center_id === workCenterId)
          .map((e) => ({ value: e.id, label: e.name })),
        motifs: list(DOWNTIME_MOTIFS, "motif"),
        stopTypes: list(DOWNTIME_TYPES, "type"),
        classifications: list(DOWNTIME_CLASSIFICATIONS, "classification"),
        wasteProduction: waste.categoriesFor("daily").map((c) => ({ value: c, label: waste.label(c) })),
        wastePacking: waste.categoriesFor("conditionnement").map((c) => ({ value: c, label: waste.label(c) })),
        runs: rowsOf("runs", "runs").map((r) => ({ value: r.id as string, label: runLabel(r) })),
        packingRows: rowsOf("packing", "rows").map((r) => ({
          value: r.id as string,
          label: String(r.lot_number || orderById.get(String(r.of_id))?.reference || String(r.id).slice(-6)),
        })),
        siloSides: [
          { value: "production", label: label({ en: "Production", fr: "Production" }) },
          { value: "packing", label: label({ en: "Packing", fr: "Conditionnement" }) },
        ],
        siloPhases: [
          { value: "start", label: label({ en: "Start", fr: "Début" }) },
          { value: "end", label: label({ en: "End", fr: "Fin" }) },
        ],
        lineStates: [
          { value: "running", label: label({ en: "Running", fr: "En marche" }) },
          { value: "stopped", label: label({ en: "Stopped", fr: "En arrêt" }) },
        ],
        checkStates: [
          { value: "good", label: label({ en: "Good", fr: "Bon" }) },
          { value: "not_good", label: label({ en: "Not good", fr: "Non bon" }) },
        ],
      };
    },
    // `waste` and `label` are rebuilt every render; what they read is captured by their own deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [orders.data, products.data, classifications.data, locations.data, molds.data, equipment.data, partners.data, waste.types, t],
  );

  return {
    workCenters: workCenters.data,
    workCentersLoading: workCenters.isLoading,
    windows: settings.data?.shift_windows ?? [],
    activeEquipment,
    reportCountByLineDate,
    buildOptions,
  };
}
