/**
 * Units for production figures.
 *
 * Every quantity in the production module either moves stock or feeds a
 * calculation that does, so a bare number is genuinely ambiguous — 500 of
 * semolina is a very different deduction in kg than in tonnes. Two sources:
 *
 * - a figure tied to a **product** takes that product's unit of measure, which
 *   is the same unit the warehouse deducts in;
 * - a **metered utility** has no product, so it carries a fixed unit that
 *   matches how the plant meters it.
 */

/** Utilities have no product behind them, so their units are fixed. */
export const UTILITY_UNITS = {
  water: "L",
  fuel: "L",
  electricity: "kWh",
} as const;

export interface UomLike {
  id: string;
  code: string;
  /**
   * How the unit prints. Optional so an older payload still resolves to
   * something -- `code` is the fallback, and a technical label beats a blank.
   */
  symbol?: string | null;
  /** Whether a quantity in this unit must be a whole number. Optional so an
   * older payload without the field simply behaves as "not integer-only". */
  is_integer_only?: boolean;
}

export interface ProductLike {
  id: string;
  uom_id: string;
}

/**
 * The unit a product is counted in. Returns null rather than a guess when the
 * product or its unit is unknown — a wrong unit is worse than no unit.
 */
export function productUnit(
  productId: string | null | undefined,
  products: ProductLike[],
  uoms: UomLike[],
): string | null {
  if (!productId) return null;
  const product = products.find((p) => p.id === productId);
  if (!product) return null;
  const uom = uoms.find((u) => u.id === product.uom_id);
  return uom ? uom.symbol || uom.code : null;
}

/**
 * Whether a product's unit forces a whole-number quantity -- a carton or a
 * pièce, never a kg or a litre. False (not null) when the product or its unit
 * is unknown, since the caller needs a plain yes/no to decide an input's
 * `step`, and "unknown" is safest treated as "don't constrain".
 */
export function productRequiresIntegerQuantity(
  productId: string | null | undefined,
  products: ProductLike[],
  uoms: UomLike[],
): boolean {
  if (!productId) return false;
  const product = products.find((p) => p.id === productId);
  const uom = product ? uoms.find((u) => u.id === product.uom_id) : undefined;
  return uom?.is_integer_only ?? false;
}

/**
 * The one unit shared by a set of products, or null if they disagree.
 *
 * Totals that span several orders — the cockpit's figures — are only meaningful
 * in a unit when every order behind them uses the same one. An unknown product
 * in the set is enough to withhold the unit: labelling a partly-unknown sum is
 * how a wrong number gets believed.
 */
export function commonUnit(
  productIds: (string | null | undefined)[],
  products: ProductLike[],
  uoms: UomLike[],
): string | null {
  if (productIds.length === 0) return null;
  const units = new Set(productIds.map((id) => productUnit(id, products, uoms)));
  if (units.size !== 1) return null;
  return [...units][0];
}

/**
 * Units written as a word rather than a symbol agree with the number in French,
 * so "1 pièce" but "36 pièces". A symbol never does: "36 kgs" is wrong.
 *
 * The test is the shape of the unit itself -- three or more letters and nothing
 * else -- rather than a list of known words, so a unit a tenant adds later
 * behaves without anyone editing this file. Anything already ending in `s`
 * is left alone.
 */
export function pluralizeUnit(unit: string, value: number): string {
  if (Math.abs(value) < 2) return unit;
  if (!/^\p{L}{3,}$/u.test(unit) || /s$/i.test(unit)) return unit;
  return `${unit}s`;
}

/** `1 250 kg`, `36 pièces`, or just the number when the unit is unknown. */
export function formatQuantity(value: number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined) return "—";
  const rounded = Math.round(value * 1000) / 1000;
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(rounded);
  return unit ? `${formatted} ${pluralizeUnit(unit, rounded)}` : formatted;
}

/**
 * Minutes as a duration a person reads at a glance.
 *
 * Under an hour it stays in minutes, because that is how the line records a
 * stoppage. Beyond that it rolls up into days and hours — "1 j 3 h 20 min" is
 * legible in a way that "1640 min" is not.
 */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} min`;

  const days = Math.floor(total / (60 * 24));
  const hours = Math.floor((total % (60 * 24)) / 60);
  const remainder = total % 60;

  const parts: string[] = [];
  if (days > 0) parts.push(`${days} j`);
  if (hours > 0) parts.push(`${hours} h`);
  // A trailing zero adds nothing once the value is already in hours or days.
  if (remainder > 0) parts.push(`${remainder} min`);
  return parts.join(" ");
}

/**
 * Quantities of different items, added up only where addition is honest.
 *
 * Waste is now recorded per item, and items are stocked in whatever unit they
 * are counted in — semoule in tonnes, rebut in kilos, cartons and scotch in
 * pieces. A single total across those is not a smaller truth, it is not a number
 * at all.
 *
 * Within one measurement category it *is* addable, because `ratio_to_base` says
 * how the units relate: a tonne is a thousand kilos, and that is a fact of the
 * unit rather than an assumption about the plant. So quantities are converted to
 * each category's base unit and totalled there, and categories stay apart.
 * Items whose product or unit is unknown are dropped rather than guessed at —
 * the caller is told how much was dropped so it can be shown, not hidden.
 */
export interface CategoryTotal {
  /** The base unit's printed form, e.g. `kg` for the weight category. */
  unit: string;
  value: number;
}

export interface QuantityByProduct {
  product_id: string | null;
  quantity: number;
}

export interface CategorizedUom extends UomLike {
  category: string;
  ratio_to_base: number;
}

export interface CategorizedProduct extends ProductLike {
  id: string;
}

/** The unit a category is totalled in: the one whose ratio to base is 1. */
function baseUomOf(category: string, uoms: CategorizedUom[]): CategorizedUom | null {
  const inCategory = uoms.filter((u) => u.category === category);
  return inCategory.find((u) => Number(u.ratio_to_base) === 1) ?? inCategory[0] ?? null;
}

export function totalsByUomCategory(
  entries: QuantityByProduct[],
  products: (CategorizedProduct & { uom_id: string })[],
  uoms: CategorizedUom[],
): { totals: CategoryTotal[]; unresolved: number } {
  const byCategory = new Map<string, number>();
  let unresolved = 0;

  for (const entry of entries) {
    const product = entry.product_id ? products.find((p) => p.id === entry.product_id) : undefined;
    const uom = product ? uoms.find((u) => u.id === product.uom_id) : undefined;
    if (!uom) {
      unresolved += entry.quantity;
      continue;
    }
    const inBase = entry.quantity * Number(uom.ratio_to_base);
    byCategory.set(uom.category, (byCategory.get(uom.category) ?? 0) + inBase);
  }

  const totals: CategoryTotal[] = [];
  for (const [category, value] of byCategory) {
    const base = baseUomOf(category, uoms);
    totals.push({ unit: base ? base.symbol || base.code : category, value });
  }
  totals.sort((a, b) => b.value - a.value);
  return { totals, unresolved };
}

/**
 * A quantity of one item expressed in another item's unit, or null when the two
 * cannot be compared — different categories, or a unit nobody recorded.
 *
 * This is what lets a waste ratio exist at all: waste is weighed in kilos and
 * semoule is poured in tonnes, so the two only divide once one is restated in
 * the other's unit.
 */
export function convertQuantity(
  quantity: number,
  fromProductId: string | null | undefined,
  toProductId: string | null | undefined,
  products: (CategorizedProduct & { uom_id: string })[],
  uoms: CategorizedUom[],
): number | null {
  const from = uoms.find((u) => u.id === products.find((p) => p.id === fromProductId)?.uom_id);
  const to = uoms.find((u) => u.id === products.find((p) => p.id === toProductId)?.uom_id);
  if (!from || !to || from.category !== to.category) return null;
  const toRatio = Number(to.ratio_to_base);
  if (toRatio === 0) return null;
  return (quantity * Number(from.ratio_to_base)) / toRatio;
}
