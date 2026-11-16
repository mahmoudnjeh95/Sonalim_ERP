import { BASE_URL, apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";

export interface SalesSettings {
  default_vat_rate: string;
  max_discount_rate: string;
  quote_validity_days: number;
  may_exceed_discount?: boolean;
}

export interface PriceList {
  id: string;
  name: string;
  valid_from: string | null;
  valid_to: string | null;
  is_default: boolean;
  active: boolean;
  note: string | null;
  item_count: number;
  customer_count: number;
}

export interface PriceListItem {
  id: string;
  product_id: string;
  sku: string;
  product_name: string;
  min_quantity: string;
  unit_price: string;
  catalog_price: string;
}

export interface PriceListDetail extends PriceList {
  items: PriceListItem[];
}

export interface PriceListInput {
  name: string;
  valid_from?: string | null;
  valid_to?: string | null;
  is_default: boolean;
  active: boolean;
  note?: string | null;
}

export interface CustomerPricing {
  partner_id: string;
  partner_name?: string;
  price_list_id: string | null;
  price_list_name: string | null;
  discount_rate: string;
}

export interface ResolvedPrice {
  product_id: string;
  quantity: string;
  unit_price: string;
  source: "price_list" | "catalog";
  price_list_id: string | null;
  price_list_name: string | null;
  min_quantity: string | null;
  discount_rate: string;
}

export interface ImportPreview {
  items: { product_id: string; sku: string; min_quantity: string; unit_price: string }[];
  errors: { row: number; message: string; message_fr: string }[];
}

export const SALES_SETTINGS_QUERY_KEY = ["sales", "settings"] as const;
export const PRICE_LISTS_QUERY_KEY = ["sales", "price-lists"] as const;
export const CUSTOMER_PRICING_QUERY_KEY = ["sales", "customer-pricing"] as const;

export const getSalesSettings = (token: string) => apiFetch<SalesSettings>("/sales/settings", { token });
export const updateSalesSettings = (token: string, body: Partial<Omit<SalesSettings, "may_exceed_discount">>) =>
  apiFetch<SalesSettings>("/sales/settings", { method: "PUT", token, body });

export const listPriceLists = (token: string) => apiFetch<PriceList[]>("/sales/price-lists", { token });
export const getPriceList = (token: string, id: string) => apiFetch<PriceListDetail>(`/sales/price-lists/${id}`, { token });
export const createPriceList = (token: string, body: PriceListInput) =>
  apiFetch<PriceListDetail>("/sales/price-lists", { method: "POST", token, body });
export const updatePriceList = (token: string, id: string, body: PriceListInput) =>
  apiFetch<PriceListDetail>(`/sales/price-lists/${id}`, { method: "PATCH", token, body });
export const deletePriceList = (token: string, id: string) => apiFetch<void>(`/sales/price-lists/${id}`, { method: "DELETE", token });
export const replacePriceItems = (token: string, id: string, items: { product_id: string; min_quantity: number; unit_price: number }[]) =>
  apiFetch<PriceListDetail>(`/sales/price-lists/${id}/items`, { method: "PUT", token, body: { items } });
export const importPriceItems = (token: string, id: string, body: { filename: string; content_base64: string; commit: boolean }) =>
  apiFetch<ImportPreview & { price_list?: PriceListDetail }>(`/sales/price-lists/${id}/import`, { method: "POST", token, body });

export async function exportPriceList(token: string, id: string, format: "csv" | "xlsx", lang: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/sales/price-lists/${id}/export?format=${format}&lang=${lang}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}

export const listCustomerPricing = (token: string) => apiFetch<CustomerPricing[]>("/sales/customer-pricing", { token });
export const getCustomerPricing = (token: string, partnerId: string) =>
  apiFetch<CustomerPricing>(`/sales/customer-pricing/${partnerId}`, { token });
export const setCustomerPricing = (token: string, partnerId: string, body: { price_list_id: string | null; discount_rate: number }) =>
  apiFetch<CustomerPricing>(`/sales/customer-pricing/${partnerId}`, { method: "PUT", token, body });

export const resolvePrices = (token: string, body: { partner_id?: string | null; on?: string; items: { product_id: string; quantity: number }[] }) =>
  apiFetch<ResolvedPrice[]>("/sales/prices/resolve", { method: "POST", token, body });
