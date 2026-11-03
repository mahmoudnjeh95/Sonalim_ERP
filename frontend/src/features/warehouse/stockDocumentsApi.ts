import { apiFetch } from "../../lib/api";

export type VoucherType = "receipt" | "issue" | "return" | "transfer";
export type VoucherStatus = "draft" | "posted" | "cancelled";

export interface VoucherLine {
  id?: string;
  product_id: string;
  quantity: string | number;
  unit_cost?: string | number | null;
}

export interface Voucher {
  id: string;
  number: string | null;
  type: VoucherType;
  status: VoucherStatus;
  source_location_id: string | null;
  dest_location_id: string | null;
  partner_id: string | null;
  ref_type: string | null;
  ref_id: string | null;
  return_of_voucher_id: string | null;
  note: string | null;
  created_at: string;
  lines?: VoucherLine[];
  warnings?: { code: string; product_id: string; on_hand: string; minimum: string }[];
}

export interface VoucherInput {
  type: VoucherType;
  source_location_id?: string;
  dest_location_id?: string;
  return_of_voucher_id?: string;
  note?: string;
  lines: { product_id: string; quantity: number; unit_cost?: number }[];
}

export interface InventoryLine {
  id: string;
  product_id: string;
  sku: string;
  name: string;
  theoretical_qty: string;
  count_1: string | null;
  count_2: string | null;
  count_3: string | null;
  final_qty: string | null;
  variance: string | null;
  observation: string | null;
}

export interface Inventory {
  id: string;
  number: string;
  location_id: string;
  type: "full" | "interim";
  status: "open" | "closed" | "cancelled";
  note: string | null;
  opened_at: string;
  lines?: InventoryLine[];
}

export const listVouchers = (token: string, type?: VoucherType) =>
  apiFetch<Voucher[]>(`/warehouse/vouchers${type ? `?type=${type}` : ""}`, { token });
export const getVoucher = (token: string, id: string) => apiFetch<Voucher>(`/warehouse/vouchers/${id}`, { token });
export const createVoucher = (token: string, body: VoucherInput) => apiFetch<Voucher>("/warehouse/vouchers", { method: "POST", token, body });
export const postVoucher = (token: string, id: string) => apiFetch<Voucher>(`/warehouse/vouchers/${id}/post`, { method: "POST", token });
export const cancelVoucher = (token: string, id: string) => apiFetch<Voucher>(`/warehouse/vouchers/${id}/cancel`, { method: "POST", token });

export const listInventories = (token: string) => apiFetch<Inventory[]>("/warehouse/inventories", { token });
export const getInventory = (token: string, id: string) => apiFetch<Inventory>(`/warehouse/inventories/${id}`, { token });
export const openInventory = (token: string, body: { location_id: string; type: "full" | "interim"; note?: string }) =>
  apiFetch<Inventory>("/warehouse/inventories", { method: "POST", token, body });
export const recordCount = (
  token: string,
  inventoryId: string,
  lineId: string,
  body: { which: 1 | 2 | 3; quantity: number | null; observation?: string },
) => apiFetch<Inventory>(`/warehouse/inventories/${inventoryId}/lines/${lineId}/count`, { method: "PATCH", token, body });
export const addInventoryLine = (token: string, inventoryId: string, productId: string) =>
  apiFetch<Inventory>(`/warehouse/inventories/${inventoryId}/lines`, { method: "POST", token, body: { product_id: productId } });
export const closeInventory = (token: string, id: string) => apiFetch<Inventory>(`/warehouse/inventories/${id}/close`, { method: "POST", token });
export const cancelInventory = (token: string, id: string) => apiFetch<Inventory>(`/warehouse/inventories/${id}/cancel`, { method: "POST", token });
