import { Boxes, Disc3, Film, Layers, Package, Ribbon, Scroll, Wheat, type LucideIcon } from "lucide-react";
import type { PackagingKind, ProductCategory } from "../../features/production/api";

/**
 * One glyph per product category and per packaging kind, so a category is
 * recognisable at a glance in a filter row, a badge or a table without
 * reading the word. Same icon everywhere: the stock table, the product
 * list, the warehouse overview and the classification screen.
 */
export const CATEGORY_ICON: Record<ProductCategory, LucideIcon> = {
  raw_material: Wheat,
  semi_finished: Layers,
  packaging_component: Package,
  finished_good: Boxes,
};

export const PACKAGING_KIND_ICON: Record<PackagingKind, LucideIcon> = {
  film: Film,
  carton: Package,
  bobine: Disc3,
  scotch: Scroll,
  ruban: Ribbon,
};

export function CategoryIcon({ category, className = "h-3.5 w-3.5" }: { category: ProductCategory | string; className?: string }) {
  const Icon = CATEGORY_ICON[category as ProductCategory];
  if (!Icon) return null;
  return <Icon className={className} aria-hidden />;
}

export function PackagingKindIcon({ kind, className = "h-3.5 w-3.5" }: { kind: PackagingKind | string; className?: string }) {
  const Icon = PACKAGING_KIND_ICON[kind as PackagingKind];
  if (!Icon) return null;
  return <Icon className={className} aria-hidden />;
}
