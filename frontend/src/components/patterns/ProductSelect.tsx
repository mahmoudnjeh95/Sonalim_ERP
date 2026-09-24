import * as React from "react";
import { Select } from "../ui/select";
import {
  filterCatalog,
  groupCatalog,
  useCatalogLabels,
  type CatalogFilter,
  type CatalogProduct,
} from "../../features/products/catalog";

export interface ProductSelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  products: CatalogProduct[];
  /** Which part of the catalog this picker is for -- "the cartons", "raw materials". */
  filter?: CatalogFilter;
  /** The empty first option. Defaults to a dash. */
  placeholder?: string;
  /** Extra options appended after the products (e.g. "+ New product"). */
  trailing?: React.ReactNode;
  /** How a product prints. Defaults to its name. */
  optionLabel?: (product: CatalogProduct) => string;
}

/**
 * A product dropdown that shows the catalog the way the plant thinks about it:
 * grouped by category and, for packaging, by kind -- so picking a carton never
 * means scrolling past every film reel and every finished pasta. Pass `filter`
 * to restrict the list to the categories a field can legitimately take.
 *
 * A native `<select>` with `<optgroup>`s, so it registers with react-hook-form
 * exactly like `Select` does.
 */
export const ProductSelect = React.forwardRef<HTMLSelectElement, ProductSelectProps>(
  ({ products, filter, placeholder = "—", trailing, optionLabel, ...props }, ref) => {
    const labels = useCatalogLabels();
    const groups = groupCatalog(filterCatalog(products, filter), labels);
    const label = optionLabel ?? ((product: CatalogProduct) => product.name);
    return (
      <Select ref={ref} {...props}>
        <option value="">{placeholder}</option>
        {groups.length === 1
          ? groups[0].products.map((product) => (
              <option key={product.id} value={product.id}>
                {label(product)}
              </option>
            ))
          : groups.map((group) => (
              <optgroup key={group.key} label={group.label}>
                {group.products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {label(product)}
                  </option>
                ))}
              </optgroup>
            ))}
        {trailing}
      </Select>
    );
  },
);
ProductSelect.displayName = "ProductSelect";
