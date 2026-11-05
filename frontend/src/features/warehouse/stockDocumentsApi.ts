import { apiErrorFromResponse, apiFetch, BASE_URL, networkError } from "../../lib/api";

export type VoucherType = "receipt" | "issue" | "return" | "transfer" | "delivery";
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
  from_voucher_id: string | null;
  billable: boolean;
  document_date: string;
  note: string | null;
  created_at: string;
  lines?: VoucherLine[];
  warnings?: { code: string; product_id: string; on_hand: string; minimum: string }[];
}

export interface VoucherInput {
  type: VoucherType;
  source_location_id?: string;
  dest_location_id?: string;
  partner_id?: string;
  return_of_voucher_id?: string;
  note?: string;
  document_date?: string;
  lines: { product_id: string; quantity: number; unit_cost?: number }[];
}

export interface UnvoucheredPurchaseReceipt {
  receipt_id: string;
  received_at: string;
  lines: number;
}

export const listVouchers = (token: string, type?: VoucherType) =>
  apiFetch<Voucher[]>(`/warehouse/vouchers${type ? `?type=${type}` : ""}`, { token });
export const getVoucher = (token: string, id: string) => apiFetch<Voucher>(`/warehouse/vouchers/${id}`, { token });
export const createVoucher = (token: string, body: VoucherInput) => apiFetch<Voucher>("/warehouse/vouchers", { method: "POST", token, body });
export const updateVoucher = (token: string, id: string, body: Omit<VoucherInput, "type" | "return_of_voucher_id">) =>
  apiFetch<Voucher>(`/warehouse/vouchers/${id}`, { method: "PATCH", token, body });
export const postVoucher = (token: string, id: string) => apiFetch<Voucher>(`/warehouse/vouchers/${id}/post`, { method: "POST", token });
export const cancelVoucher = (token: string, id: string) => apiFetch<Voucher>(`/warehouse/vouchers/${id}/cancel`, { method: "POST", token });
export const generateDeliveryNote = (token: string, id: string) =>
  apiFetch<Voucher>(`/warehouse/vouchers/${id}/delivery-note`, { method: "POST", token, body: {} });
export const listUnvoucheredPurchaseReceipts = (token: string) => apiFetch<UnvoucheredPurchaseReceipt[]>("/warehouse/vouchers/purchase-receipts", { token });
export const createReceiptFromPurchaseReceipt = (token: string, receiptId: string) =>
  apiFetch<Voucher>(`/warehouse/vouchers/from-purchase-receipt/${receiptId}`, { method: "POST", token });

// ---- attached files ------------------------------------------------------------------------------
export type AttachmentEntity = "voucher" | "cycle_count";

export interface DocumentAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export const listAttachments = (token: string, entity: AttachmentEntity, id: string) =>
  apiFetch<DocumentAttachment[]>(`/warehouse/attachments/${entity}/${id}`, { token });
export const addAttachment = (token: string, entity: AttachmentEntity, id: string, body: { filename: string; content_type: string; content_base64: string }) =>
  apiFetch<DocumentAttachment>(`/warehouse/attachments/${entity}/${id}`, { method: "POST", token, body });
export const deleteAttachment = (token: string, entity: AttachmentEntity, id: string, attachmentId: string) =>
  apiFetch<void>(`/warehouse/attachments/${entity}/${id}/${attachmentId}`, { method: "DELETE", token });

async function fetchBlob(token: string, path: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}

export const downloadAttachment = (token: string, entity: AttachmentEntity, id: string, attachmentId: string) =>
  fetchBlob(token, `/warehouse/attachments/${entity}/${id}/${attachmentId}`);

// ---- reports -------------------------------------------------------------------------------------
export interface MovementRow {
  created_at: string;
  move_type: string;
  sku: string;
  product: string;
  location: string | null;
  quantity: string | number;
  unit_cost: string | number | null;
  reference: string | null;
  voucher_number: string | null;
  voucher_type: VoucherType | null;
}

export interface MovementsFilter {
  move_type?: string;
  location_id?: string;
  date_from?: string;
  date_to?: string;
}

function movementsQuery(filter: MovementsFilter, format?: "csv" | "xlsx") {
  const query = new URLSearchParams();
  Object.entries(filter).forEach(([key, value]) => value && query.set(key, value));
  if (format) query.set("format", format);
  const suffix = query.toString();
  return `/warehouse/reports/movements${suffix ? `?${suffix}` : ""}`;
}

export const getMovementsReport = (token: string, filter: MovementsFilter) => apiFetch<MovementRow[]>(movementsQuery(filter), { token });
export const downloadMovementsReport = (token: string, filter: MovementsFilter, format: "csv" | "xlsx") => fetchBlob(token, movementsQuery(filter, format));
export const downloadValuedStock = (token: string, format: "csv" | "xlsx") => fetchBlob(token, `/warehouse/reports/valued-stock?format=${format}`);

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// ---- valuation method ----------------------------------------------------------------------------
export type ValuationMethod = "fifo" | "average";

export const getValuationMethod = (token: string) => apiFetch<{ method: ValuationMethod }>("/warehouse/settings/valuation-method", { token });
export const setValuationMethod = (token: string, method: ValuationMethod) =>
  apiFetch<{ method: ValuationMethod }>("/warehouse/settings/valuation-method", { method: "PUT", token, body: { method } });
