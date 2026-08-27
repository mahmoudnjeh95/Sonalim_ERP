import { apiFetch } from "../../lib/api";
import type { ExpiryDatePolicy, LotSerialTracking, Product } from "../warehouse/api";

export interface CreateProductInput {
  sku: string;
  name: string;
  uom_id: string;
  net_weight_grams?: number;
  is_sellable?: boolean;
  is_purchasable?: boolean;
  lot_serial_tracking?: LotSerialTracking;
  expiry_date_policy?: ExpiryDatePolicy;
  description?: string;
  default_location_id?: string;
  stock_alert_threshold?: number;
  internal_note?: string;
  selling_price?: number;
  min_selling_price?: number;
  purchase_price?: number;
  tax_rate?: number;
  accounting_code_sale?: string;
  accounting_code_sale_export?: string;
  accounting_code_purchase?: string;
  accounting_code_purchase_import?: string;
}

export type UpdateProductInput = Partial<CreateProductInput>;

export function createProduct(token: string, input: CreateProductInput) {
  return apiFetch<Product>("/core/products", { method: "POST", token, body: input });
}

export function updateProduct(token: string, productId: string, input: UpdateProductInput) {
  return apiFetch<Product>(`/core/products/${productId}`, { method: "PATCH", token, body: input });
}

// --- Tags -------------------------------------------------------------------------------

export interface ProductTag {
  id: string;
  name: string;
}

export function listProductTags(token: string) {
  return apiFetch<ProductTag[]>("/core/product-tags", { token });
}

export function createProductTag(token: string, name: string) {
  return apiFetch<ProductTag>("/core/product-tags", { method: "POST", token, body: { name } });
}

export function listTagsForProduct(token: string, productId: string) {
  return apiFetch<ProductTag[]>(`/core/products/${productId}/tags`, { token });
}

export function setProductTags(token: string, productId: string, tagIds: string[]) {
  return apiFetch<ProductTag[]>(`/core/products/${productId}/tags`, { method: "PUT", token, body: { tag_ids: tagIds } });
}

// --- Variant attributes -------------------------------------------------------------------

export interface ProductAttribute {
  id: string;
  name: string;
}

export function listProductAttributes(token: string) {
  return apiFetch<ProductAttribute[]>("/core/product-attributes", { token });
}

export function createProductAttribute(token: string, name: string) {
  return apiFetch<ProductAttribute>("/core/product-attributes", { method: "POST", token, body: { name } });
}

export interface ProductAttributeValue {
  id: string;
  attribute_id: string;
  value: string;
}

export function listProductAttributeValues(token: string, attributeId: string) {
  return apiFetch<ProductAttributeValue[]>(`/core/product-attributes/${attributeId}/values`, { token });
}

export function createProductAttributeValue(token: string, attributeId: string, value: string) {
  return apiFetch<ProductAttributeValue>(`/core/product-attributes/${attributeId}/values`, {
    method: "POST",
    token,
    body: { value },
  });
}

export function listProductVariants(token: string, productId: string) {
  return apiFetch<Product[]>(`/core/products/${productId}/variants`, { token });
}

export function createProductVariant(token: string, productId: string, input: { sku: string; name: string; attribute_value_ids: string[] }) {
  return apiFetch<Product>(`/core/products/${productId}/variants`, { method: "POST", token, body: input });
}

// --- Lots/serials (warehouse module) -------------------------------------------------------

export type LotStatus = "active" | "consumed" | "expired";

export interface Lot {
  id: string;
  product_id: string;
  lot_number: string;
  status: LotStatus;
  expiry_date: string | null;
  produced_at: string | null;
  source_type: string | null;
  source_id: string | null;
}

export function listLots(token: string, productId?: string) {
  const query = productId ? `?product_id=${productId}` : "";
  return apiFetch<Lot[]>(`/warehouse/lots${query}`, { token });
}

export function listLotStatuses(token: string) {
  return apiFetch<string[]>("/warehouse/lots/statuses", { token });
}

export function transitionLot(token: string, lotId: string, newStatus: LotStatus) {
  return apiFetch<Lot>(`/warehouse/lots/${lotId}/transition`, { method: "POST", token, body: { new_status: newStatus } });
}

export interface LotStockRow {
  lot_id: string;
  product_id: string;
  lot_number: string;
  status: LotStatus;
  expiry_date: string | null;
  location_id: string;
  quantity_on_hand: number;
}

export function listLotStock(token: string, productId?: string) {
  const query = productId ? `?product_id=${productId}` : "";
  return apiFetch<LotStockRow[]>(`/warehouse/lot-stock${query}`, { token });
}
