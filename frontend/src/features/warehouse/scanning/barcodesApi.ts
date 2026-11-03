import { apiFetch } from "../../../lib/api";

export type BarcodeType = "gtin" | "internal";

export interface ProductBarcode {
  id: string;
  product_id: string;
  barcode: string;
  barcode_type: BarcodeType;
  units_per_scan: number;
  label: string | null;
  created_by: string;
  created_at: string;
}

export type ScanResolution =
  | { code: string; kind: "unknown" }
  | {
      code: string;
      kind: "product";
      matched_by: "gs1" | "barcode" | "sku";
      product_id: string;
      quantity: number;
      lot_number?: string | null;
      lot_id?: string | null;
      expiry_date?: string | null;
    }
  | { code: string; kind: "location"; matched_by: "location_code"; location_id: string }
  | { code: string; kind: "lot"; matched_by: "lot_number"; lot_id: string; product_id: string };

export const BARCODES_QUERY_KEY = ["warehouse", "productBarcodes"] as const;

export function scanResolveQueryKey(code: string) {
  return ["warehouse", "scanResolve", code] as const;
}

export function resolveScan(token: string, code: string) {
  return apiFetch<ScanResolution>(`/warehouse/scan/resolve?${new URLSearchParams({ code })}`, { token });
}

export function listBarcodes(token: string) {
  return apiFetch<ProductBarcode[]>("/warehouse/product-barcodes", { token });
}

export interface BarcodeInput {
  product_id: string;
  barcode: string;
  barcode_type: BarcodeType;
  units_per_scan: number;
  label?: string | null;
}

export function createBarcode(token: string, input: BarcodeInput) {
  return apiFetch<ProductBarcode>("/warehouse/product-barcodes", { method: "POST", token, body: input });
}

export function updateBarcode(token: string, barcodeId: string, input: Partial<Omit<BarcodeInput, "product_id">>) {
  return apiFetch<ProductBarcode>(`/warehouse/product-barcodes/${barcodeId}`, { method: "PATCH", token, body: input });
}

export function deleteBarcode(token: string, barcodeId: string) {
  return apiFetch<void>(`/warehouse/product-barcodes/${barcodeId}`, { method: "DELETE", token });
}
