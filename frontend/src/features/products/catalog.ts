/**
 * The product catalog as every picker in the app should see it: each product
 * together with its category (raw material, packaging component, semi-finished,
 * finished good) and, for packaging, its kind (film, carton, bobine, scotch,
 * ruban).
 *
 * The category itself lives in the production module (Production > Product
 * classifications) -- the product master in core only knows the pasta type
 * PL/PC. This hook joins the two once so a dropdown can list "the cartons"
 * or "the semolina" instead of every product the plant has ever created, and
 * so screens outside production (warehouse, sales, procurement) read the same
 * classification the shift form does.
 */
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { listProducts, type Product } from "../warehouse/api";
import {
  listClassifications,
  type PackagingFormat,
  type PackagingKind,
  type ProductCategory,
  type ProductClassification,
} from "../production/api";

export const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
export const CLASSIFICATIONS_QUERY_KEY = ["production", "product-classifications"] as const;
const VIEW_CLASSIFICATIONS_PERMISSION = "production.view_product_classifications";

/** A product with its category resolved. `category` is null when nobody has classified it yet. */
export interface CatalogProduct extends Product {
  category: ProductCategory | null;
  packaging_kind: PackagingKind | null;
  packaging_format: PackagingFormat | null;
  is_regrind: boolean;
  is_water: boolean;
  is_energy: boolean;
}

/** Display order of the groups in a picker: what the plant consumes first, what it makes last. */
export const CATEGORY_ORDER: ProductCategory[] = ["raw_material", "packaging_component", "semi_finished", "finished_good"];
export const PACKAGING_KIND_ORDER: PackagingKind[] = ["film", "carton", "bobine", "scotch", "ruban"];

export type CatalogFilter = {
  /** Keep only these categories. Omit for every category. */
  categories?: ProductCategory[];
  /** Keep only packaging of these kinds (implies `packaging_component`). */
  packagingKinds?: PackagingKind[];
  /** Whether products nobody has classified are kept. Defaults to true so a
   * new product is never silently impossible to pick -- it lands in the
   * "Unclassified" group instead. */
  includeUnclassified?: boolean;
};

export function joinCatalog(products: Product[], classifications: ProductClassification[]): CatalogProduct[] {
  const byProduct = new Map(classifications.map((c) => [c.product_id, c]));
  return products.map((product) => {
    const classification = byProduct.get(product.id);
    return {
      ...product,
      category: classification?.category ?? null,
      packaging_kind: classification?.packaging_kind ?? null,
      packaging_format: classification?.packaging_format ?? null,
      is_regrind: classification?.is_regrind ?? false,
      is_water: classification?.is_water ?? false,
      is_energy: classification?.is_energy ?? false,
    };
  });
}

export function filterCatalog(products: CatalogProduct[], filter: CatalogFilter = {}): CatalogProduct[] {
  const includeUnclassified = filter.includeUnclassified ?? true;
  return products.filter((product) => {
    if (product.category === null) return includeUnclassified && !filter.packagingKinds;
    if (filter.packagingKinds) {
      return product.category === "packaging_component" && product.packaging_kind !== null && filter.packagingKinds.includes(product.packaging_kind);
    }
    if (filter.categories) return filter.categories.includes(product.category);
    return true;
  });
}

export interface CatalogGroup {
  key: string;
  label: string;
  products: CatalogProduct[];
}

/**
 * Products bucketed the way a picker shows them: one group per category, with
 * packaging further split by kind (a carton picker should not scroll past the
 * film reels), and an "Unclassified" tail for products still waiting on a
 * classification. Empty groups are dropped; products are sorted by name.
 */
export function groupCatalog(products: CatalogProduct[], labels: CatalogLabels): CatalogGroup[] {
  const groups: CatalogGroup[] = [];
  const sorted = [...products].sort((a, b) => a.name.localeCompare(b.name));
  for (const category of CATEGORY_ORDER) {
    if (category === "packaging_component") {
      for (const kind of PACKAGING_KIND_ORDER) {
        const items = sorted.filter((p) => p.category === category && p.packaging_kind === kind);
        if (items.length > 0) groups.push({ key: `packaging:${kind}`, label: `${labels.category[category]} · ${labels.packagingKind[kind]}`, products: items });
      }
      const untyped = sorted.filter((p) => p.category === category && p.packaging_kind === null);
      if (untyped.length > 0) groups.push({ key: "packaging:other", label: labels.category[category], products: untyped });
      continue;
    }
    const items = sorted.filter((p) => p.category === category);
    if (items.length > 0) groups.push({ key: category, label: labels.category[category], products: items });
  }
  const unclassified = sorted.filter((p) => p.category === null);
  if (unclassified.length > 0) groups.push({ key: "unclassified", label: labels.unclassified, products: unclassified });
  return groups;
}

export interface CatalogLabels {
  category: Record<ProductCategory, string>;
  packagingKind: Record<PackagingKind, string>;
  unclassified: string;
}

/** Translated names for every group a picker can show. Call once per render, like `useMoveTypeLabels`. */
export function useCatalogLabels(): CatalogLabels {
  const { t } = useI18n();
  return {
    category: {
      raw_material: t("production.classifications.category.raw_material"),
      semi_finished: t("production.classifications.category.semi_finished"),
      packaging_component: t("production.classifications.category.packaging_component"),
      finished_good: t("production.classifications.category.finished_good"),
    },
    packagingKind: {
      film: t("production.classifications.packagingKind.film"),
      carton: t("production.classifications.packagingKind.carton"),
      bobine: t("production.classifications.packagingKind.bobine"),
      scotch: t("production.classifications.packagingKind.scotch"),
      ruban: t("production.classifications.packagingKind.ruban"),
    },
    unclassified: t("products.catalog.unclassified"),
  };
}

/**
 * Products joined with their classification. Best-effort on the
 * classification side: a role that cannot see production's classifications
 * still gets the product list, just ungrouped, rather than an error.
 */
export function useProductCatalog() {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const canSeeClassifications = hasPermission(VIEW_CLASSIFICATIONS_PERMISSION);
  const products = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const classifications = useQuery({
    queryKey: CLASSIFICATIONS_QUERY_KEY,
    queryFn: () => listClassifications(token),
    enabled: canSeeClassifications,
  });
  const catalog = joinCatalog(products.data ?? [], classifications.data ?? []);
  return {
    catalog,
    products: products.data ?? [],
    classifications: classifications.data ?? [],
    isLoading: products.isLoading || (canSeeClassifications && classifications.isLoading),
    canSeeClassifications,
  };
}
