import { apiFetch } from "../../lib/api";

export interface PaymentOrderSummary {
  id: string;
  number: string;
  created_at: string;
  disbursement_number: string;
  partner_id: string;
  total: string;
  currency: string;
}

export interface PaymentOrder {
  id: string;
  number: string;
  created_at: string;
  note: string | null;
  disbursement_number: string;
  partner_id: string;
  currency: string;
  doc_date: string;
  total: string;
  transfers: { payment_id: string; amount: string; account_name: string | null; account_number: string | null; iban: string | null }[];
}

export interface TreasuryNotification {
  id: string;
  kind: string;
  ref_id: string | null;
  message_en: string;
  message_fr: string;
  created_at: string;
}

export interface InvoicePaymentOrder {
  id: string;
  number: string;
  order_date: string;
  due_date: string;
  method: string;
  partner_id: string;
  partner_name: string;
  invoice_id: string;
  invoice_number: string | null;
  supplier_invoice_number: string | null;
  invoice_date: string | null;
  amount: string | null;
  remaining: string | null;
  currency: string | null;
  employee_user_id: string;
  employee_email: string;
  department: string | null;
  note: string | null;
}

export const listInvoicePaymentOrders = (token: string) => apiFetch<InvoicePaymentOrder[]>("/treasury/invoice-payment-orders", { token });
export const createInvoicePaymentOrder = (
  token: string,
  body: { order_date: string; due_date: string; method: string; invoice_id: string; employee_user_id: string; department?: string; note?: string },
) => apiFetch<InvoicePaymentOrder>("/treasury/invoice-payment-orders", { method: "POST", token, body });
export const notifyInvoicePaymentOrder = (token: string, orderId: string, userId: string) =>
  apiFetch<{ id: string }>(`/treasury/invoice-payment-orders/${orderId}/notify`, { method: "POST", token, body: { user_id: userId } });

export const listPaymentOrders = (token: string) => apiFetch<PaymentOrderSummary[]>("/treasury/payment-orders", { token });
export const getPaymentOrder = (token: string, id: string) => apiFetch<PaymentOrder>(`/treasury/payment-orders/${id}`, { token });
export const createPaymentOrder = (token: string, disbursementId: string) =>
  apiFetch<PaymentOrder>(`/treasury/disbursements/${disbursementId}/payment-order`, { method: "POST", token, body: {} });
export const notifyPaymentOrder = (token: string, orderId: string, userId: string) =>
  apiFetch<{ id: string }>(`/treasury/payment-orders/${orderId}/notify`, { method: "POST", token, body: { user_id: userId } });
export const listNotifiableUsers = (token: string) => apiFetch<{ id: string; email: string }[]>("/treasury/notifiable-users", { token });
export const listNotifications = (token: string) => apiFetch<TreasuryNotification[]>("/treasury/notifications", { token });
export const markNotificationRead = (token: string, id: string) =>
  apiFetch<void>(`/treasury/notifications/${id}/read`, { method: "POST", token });
