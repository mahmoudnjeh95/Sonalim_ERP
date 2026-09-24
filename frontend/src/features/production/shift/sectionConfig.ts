import {
  ClipboardCheck,
  Container,
  Factory,
  Package,
  PackageX,
  Timer,
  Trash2,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { Option, OptionMap } from "./ShiftGrid";
import type { Row, SectionKey } from "./shiftApi";
import { L, type Label } from "./shiftText";

/**
 * The nine sections, described as data the way the paper fiches are laid out.
 *
 * A column's `key` is the backend column it writes to. A section is one or more
 * *parts*: a list of rows (a table the team scrolls and adds to) or a single record
 * (a small form). A row can carry a child list (a run's semoule lines).
 */
export type CellKind = "text" | "number" | "int" | "time" | "datetime" | "date" | "select" | "expression" | "readonly";

/** Where a select's choices come from; resolved by the screen from live data. */
export type OptionSource =
  | "orders"
  | "products"
  | "locations"
  | "molds"
  | "equipment"
  | "motifs"
  | "stopTypes"
  | "classifications"
  | "wasteProduction"
  | "wastePacking"
  | "runs"
  | "packingRows"
  | "siloSides"
  | "siloPhases"
  | "productsOrMp"
  | "mpVerse"
  | "moldsForShift"
  | "orderTypes"
  | "moldTypes"
  | "itemsFilm"
  | "itemsCarton"
  | "itemsBobine"
  | "itemsScotch"
  | "itemsRuban"
  | "packedProducts"
  | "lineStates"
  | "checkStates"
  | "partners"
  | "finishedProducts"
  | "shiftOrders"
  | "packingTypes";

export interface Column {
  key: string;
  label: Label;
  kind: CellKind;
  options?: OptionSource;
  /** Choices that depend on the row being edited; wins over `options`. */
  optionsFor?: (row: Row, options: OptionMap) => Option[];
  required?: boolean;
  /** For a read-only cell: what to show from the row as it is being edited, before the server has derived it. */
  valueFor?: (row: Row, options: OptionMap) => string | null;
  /** Fields cleared when this cell changes, so the server derives them again from the new value. */
  resets?: readonly string[];
  /** A number column stored in one unit but typed/shown in another: value shown = stored value * scale. */
  scale?: number;
}

export interface ChildDef {
  payloadKey: string;
  title: Label;
  addLabel: Label;
  columns: Column[];
}

export interface PartDef {
  payloadKey: string;
  shape: "rows" | "single";
  title?: Label;
  addLabel?: Label;
  columns: Column[];
  child?: ChildDef;
  /** Fields the server works out from the row; the screen never sends them back, so they follow the row on every save. */
  serverDerived?: readonly string[];
}

export interface SectionDef {
  key: SectionKey;
  icon: LucideIcon;
  /** A one-line name for the narrow progress rail. */
  short: Label;
  title: Label;
  hint: Label;
  parts: PartDef[];
}

const text = (key: string, label: Label): Column => ({ key, label, kind: "text" });
const num = (key: string, label: Label, scale?: number): Column => ({ key, label, kind: "number", scale });
const int = (key: string, label: Label): Column => ({ key, label, kind: "int" });
const time = (key: string, label: Label): Column => ({ key, label, kind: "time" });
const when = (key: string, label: Label, required = false): Column => ({ key, label, kind: "datetime", required });
const pick = (key: string, label: Label, options: OptionSource, required = false): Column => ({
  key,
  label,
  kind: "select",
  options,
  required,
});

const derived = (key: string, label: Label): Column => ({ key, label, kind: "readonly" });

/** The molds of the type (PL or PC) of the row's work order; every mold while the type is unknown. */
export function moldsForOrder(row: Row, options: OptionMap): Option[] {
  const type = options.orderTypes.find((o) => o.value === row.of_id)?.label;
  if (!type) return options.molds;
  const ofThatType = new Set(options.moldTypes.filter((m) => m.label === type).map((m) => m.value));
  return options.molds.filter((m) => ofThatType.has(m.value));
}

/** The packing type of the row's chosen product, read from the option list built from the products. */
export function packingTypeFor(row: Row, options: OptionMap): string | null {
  return options.packingTypes.find((option) => option.value === row.product_id)?.label ?? null;
}

export const SECTIONS: SectionDef[] = [
  {
    key: "runs",
    icon: Factory,
    short: L("Production", "Production"),
    title: L("Production", "Production"),
    hint: L(
      "One row per product run. A mold change starts a new row.",
      "Une ligne par production. Un changement de moule commence une nouvelle ligne.",
    ),
    parts: [
      {
        payloadKey: "versements",
        shape: "rows",
        title: L("Versement", "Versement"),
        addLabel: L("Add a versement", "Ajouter un versement"),
        serverDerived: ["location_id"],
        columns: [
          pick("product_id", L("MP versé", "MP versé"), "mpVerse", true),
          num("quantity", L("Quantity (t)", "Quantité (t)")),
        ],
      },
      {
        payloadKey: "rebroyat_versements",
        shape: "rows",
        title: L("Rebroyat", "Rebroyat"),
        addLabel: L("Add a rebroyat versement", "Ajouter un rebroyat"),
        serverDerived: ["location_id"],
        columns: [
          pick("product_id", L("Rebroyat item", "Article rebroyat"), "productsOrMp", true),
          num("quantity", L("Quantity (t)", "Quantité (t)")),
        ],
      },
      {
        payloadKey: "runs",
        shape: "rows",
        addLabel: L("Add a run", "Ajouter une production"),
        columns: [
          pick("of_id", L("Work order", "OF"), "orders", true),
          { ...pick("mold_id", L("Mold", "Moule"), "molds"), optionsFor: moldsForOrder },
          text("lot_number", L("Lot", "N° lot")),
          time("start_time", L("Start", "HD prod")),
          time("end_time", L("End", "HF prod")),
          int("production_minutes", L("Minutes run", "Minutes de marche")),
          num("dough_quantity", L("Dough (t)", "Pâte (t)")),
          num("finished_product_quantity", L("Finished (t)", "Produit fini (t)")),
          num("regrind_quantity", L("Regrind made (kg)", "Rebroyat produit (kg)"), 1000),
          pick("regrind_input_product_id", L("Regrind item", "Article rebroyat"), "productsOrMp"),
          pick("raw_material_location_id", L("Regrind store", "Magasin rebroyat"), "locations"),
          num("regrind_input_quantity", L("Regrind used (t)", "Rebroyat utilisé (t)")),
          num("water_percentage", L("Water %", "% eau")),
          num("humidity_percentage", L("Humidity %", "Humidité %")),
          num("semolina_flow_rate", L("Semoule flow (t/h)", "Débit semoule (t/h)")),
        ],
        child: {
          payloadKey: "semolina_lines",
          title: L("Semoule", "Semoule"),
          addLabel: L("Add a semoule line", "Ajouter une ligne de semoule"),
          columns: [
            pick("product_id", L("Quality", "Qualité"), "products"),
            pick("location_id", L("Silo / store", "Silo / magasin"), "locations"),
            int("bag_count", L("Bags", "Sacs")),
            num("quantity", L("Quantity (t)", "Quantité (t)")),
            text("lot_number", L("Lot", "Lot")),
          ],
        },
      },
    ],
  },
  {
    key: "waste_production",
    icon: Trash2,
    short: L("Waste & molds", "Déchets & moules"),
    title: L("Non-conforming dough and mold washing", "Pâtes non conformes et lavage des moules"),
    hint: L(
      "Dough, pressing and finished-product waste, and each mold washed.",
      "Déchets pétrin, presse et produit fini, et chaque moule lavé.",
    ),
    parts: [
      {
        payloadKey: "waste_lines",
        shape: "rows",
        title: L("Waste", "Déchets"),
        addLabel: L("Add waste", "Ajouter un déchet"),
        columns: [
          pick("category", L("Kind", "Type"), "wasteProduction", true),
          num("quantity", L("Quantity (kg)", "Quantité (kg)")),
          pick("run_id", L("Run", "Production"), "runs"),
          when("occurred_at", L("Time", "Heure")),
          text("lot_number", L("Lot", "N° lot")),
          text("note", L("Cause", "Cause")),
        ],
      },
      {
        payloadKey: "mold_washes",
        shape: "rows",
        title: L("Mold washing", "Lavage des moules"),
        addLabel: L("Add a wash", "Ajouter un lavage"),
        columns: [
          pick("mold_id", L("Mold", "Moule"), "moldsForShift"),
          when("washed_at", L("Time", "Heure")),
          text("state", L("State", "État")),
        ],
      },
    ],
  },
  {
    key: "stops",
    icon: Timer,
    short: L("Stops", "Arrêts"),
    title: L("Stops", "Arrêts"),
    hint: L(
      "Every stop of the shift, with its machine, times and what was done.",
      "Chaque arrêt du shift, avec sa machine, ses heures et l'action menée.",
    ),
    parts: [
      {
        payloadKey: "stops",
        shape: "rows",
        addLabel: L("Add a stop", "Ajouter un arrêt"),
        columns: [
          pick("equipment_id", L("Machine", "Machine"), "equipment"),
          when("started_at", L("From", "De"), true),
          when("ended_at", L("To", "À")),
          pick("downtime_type", L("Type", "Type"), "stopTypes"),
          pick("classification", L("System", "Système"), "classifications"),
          pick("motif", L("Reason", "Motif"), "motifs"),
          pick("run_id", L("Run", "Production"), "runs"),
          text("note", L("Breakdown", "Panne")),
          text("corrective_action", L("Corrective action", "Action corrective")),
        ],
      },
    ],
  },
  {
    key: "silo",
    icon: Container,
    short: L("Silo state", "État du silo"),
    title: L("Silo state", "État du silo"),
    hint: L(
      "What was in the silo and the line's state, at the start and at the end.",
      "Ce qu'il y avait dans le silo et l'état de la ligne, au début et à la fin.",
    ),
    parts: [
      {
        payloadKey: "states",
        shape: "rows",
        addLabel: L("Add a reading", "Ajouter un relevé"),
        columns: [
          pick("side", L("Side", "Côté"), "siloSides", true),
          pick("phase", L("When", "Moment"), "siloPhases", true),
          text("format", L("Format", "Format")),
          text("lot_number", L("Lot", "N° lot")),
          num("level_percent", L("Level %", "Niveau %")),
          pick("line_state", L("Line state", "État de la ligne"), "lineStates"),
        ],
      },
    ],
  },
  {
    key: "staffing",
    icon: Users,
    short: L("Staff", "Personnel"),
    title: L("Staff present", "Présence du personnel"),
    hint: L("How many people worked at each station.", "Combien de personnes à chaque poste."),
    parts: [
      {
        payloadKey: "staffing",
        shape: "single",
        columns: [
          int("control_room", L("Control room", "Salle de contrôle")),
          int("petrin", L("Pétrin", "Pétrin")),
          int("semoule", L("Semoule", "Semoule")),
          int("broyage", L("Grinding", "Broyage")),
        ],
      },
    ],
  },
  {
    key: "packing",
    icon: Package,
    short: L("Packing", "Conditionnement"),
    title: L("Packing", "Conditionnement"),
    hint: L(
      "One row per lot packed: the product, what it used and what it made.",
      "Une ligne par lot conditionné : le produit, ce qu'il a consommé, ce qu'il a produit.",
    ),
    parts: [
      {
        payloadKey: "rows",
        shape: "rows",
        serverDerived: ["run_id", "packing_type", "packets_counted", "finished_goods_location_id", "packaging_location_id"],
        addLabel: L("Add a lot", "Ajouter un lot"),
        columns: [
          { ...pick("product_id", L("Product", "Produit"), "finishedProducts", true), resets: ["of_id"] },
          pick("of_id", L("Work order", "OF"), "shiftOrders"),
          text("lot_number", L("Lot", "N° lot")),
          { ...derived("packing_type", L("Packing type", "Type de conditionnement")), valueFor: packingTypeFor },
          pick("film_product_id", L("Film type", "Type film"), "itemsFilm"),
          { key: "film_quantity", label: L("Film (kg)", "Film (kg)"), kind: "expression" },
          pick("carton_product_id", L("Carton type", "Type carton"), "itemsCarton"),
          num("carton_quantity", L("Cartons", "Cartons")),
          num("waste_carton_quantity", L("Empty cartons", "Cartons vides")),
          pick("tape_product_id", L("Reel type", "Type bobine"), "itemsBobine"),
          num("tape_quantity", L("Reels", "Bobines")),
          pick("scotch_product_id", L("Scotch type", "Type scotch"), "itemsScotch"),
          num("scotch_quantity", L("Scotch", "Scotch")),
          pick("ruban_product_id", L("Ribbon type", "Type ruban"), "itemsRuban"),
          num("ruban_quantity", L("Ribbon", "Ruban")),
        ],
      },
    ],
  },
  {
    key: "packet_checks",
    icon: ClipboardCheck,
    short: L("Packet checks", "Contrôle paquets"),
    title: L("Packet checks", "Vérification des paquets"),
    hint: L("The hourly check of the packets coming off the line.", "Le contrôle horaire des paquets en sortie de ligne."),
    parts: [
      {
        payloadKey: "checks",
        shape: "rows",
        addLabel: L("Add a check", "Ajouter un contrôle"),
        columns: [
          when("checked_at", L("Time", "Heure")),
          pick("film_state", L("Film", "Film"), "checkStates"),
          num("packet_weight_grams", L("Packet weight (g)", "Poids paquet (g)")),
          pick("long_weld", L("Long weld", "Soudure longitudinale"), "checkStates"),
          pick("vertical_weld", L("Vertical weld", "Soudure verticale"), "checkStates"),
          pick("date_print", L("Date print", "Impression date"), "checkStates"),
          text("note", L("Note", "Observation")),
        ],
      },
    ],
  },
  {
    key: "waste_packing",
    icon: PackageX,
    short: L("Packing waste", "Déchets cond."),
    title: L("Packing waste", "Déchets de conditionnement"),
    hint: L("Product, film and cartons lost while packing.", "Produit, film et cartons perdus au conditionnement."),
    parts: [
      {
        payloadKey: "waste_lines",
        shape: "rows",
        addLabel: L("Add waste", "Ajouter un déchet"),
        columns: [
          when("occurred_at", L("Time", "Heure")),
          pick("category", L("Kind", "Type"), "wastePacking", true),
          num("quantity", L("Quantity (kg)", "Quantité (kg)")),
          text("note", L("Cause", "Cause")),
        ],
      },
    ],
  },
  {
    key: "energy",
    icon: Zap,
    short: L("Energy", "Énergie"),
    title: L("Energy", "Énergie"),
    hint: L(
      "Typed once for the whole shift; it is shared across the runs by the time each one ran.",
      "Saisie une seule fois pour le shift ; elle est répartie entre les productions selon leur durée.",
    ),
    parts: [
      {
        payloadKey: "energy",
        shape: "single",
        columns: [
          num("fuel_quantity", L("Fuel (l)", "Fuel (l)")),
          pick("fuel_supplier_id", L("Fuel supplier", "Fournisseur fuel"), "partners"),
          num("gasoil_quantity", L("Gasoil (l)", "Gasoil (l)")),
          pick("gasoil_supplier_id", L("Gasoil supplier", "Fournisseur gasoil"), "partners"),
          num("gasoil_flow_rate", L("Gasoil rate (l/h)", "Débit gasoil (l/h)")),
          num("generator_hours", L("Generator hours", "Heures groupe")),
          num("electricity_quantity", L("Electricity (kWh)", "Électricité (kWh)")),
        ],
      },
    ],
  },
];

export const SECTION_BY_KEY: Record<SectionKey, SectionDef> = Object.fromEntries(
  SECTIONS.map((section) => [section.key, section]),
) as Record<SectionKey, SectionDef>;
