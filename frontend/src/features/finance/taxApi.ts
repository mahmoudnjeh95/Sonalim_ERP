import type { QueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api";

export type TaxScope = "sales" | "purchase" | "both";

export interface TaxCode {
  id: string;
  code: string;
  name_fr: string;
  name_en: string;
  rate: number;
  applies_to: TaxScope;
  exempt: boolean;
  active: boolean;
  is_default_sales: boolean;
  is_default_purchase: boolean;
}

export interface TaxCodeInput {
  code: string;
  name_fr: string;
  name_en: string;
  rate: number;
  applies_to: TaxScope;
  exempt: boolean;
}

export interface VatRateRow {
  vat_rate: number;
  base: number;
  vat: number;
  exempt: boolean;
}

export interface VatReport {
  date_from: string;
  date_to: string;
  sales_by_rate: VatRateRow[];
  sales_base: number;
  sales_vat: number;
  ledger: {
    collected_account: string | null;
    deductible_account: string | null;
    collected: number | null;
    deductible: number | null;
    payable: number | null;
  };
  warnings: ("NO_COLLECTED_VAT_ACCOUNT" | "NO_DEDUCTIBLE_VAT_ACCOUNT")[];
}

export const TAX_KEYS = {
  codes: ["finance", "tax-codes"] as const,
  report: (from: string, to: string) => ["finance", "vat-report", from, to] as const,
};

export function listTaxCodes(token: string, includeInactive = true) {
  return apiFetch<TaxCode[]>(`/finance/tax-codes?include_inactive=${includeInactive}`, { token });
}

export function createTaxCode(token: string, body: TaxCodeInput) {
  return apiFetch<TaxCode>("/finance/tax-codes", { method: "POST", token, body });
}

export function updateTaxCode(token: string, id: string, body: Partial<Omit<TaxCodeInput, "code">> & { active?: boolean }) {
  return apiFetch<TaxCode>(`/finance/tax-codes/${id}`, { method: "PATCH", token, body });
}

export function setDefaultTaxCode(token: string, id: string, side: "sales" | "purchase") {
  return apiFetch<TaxCode>(`/finance/tax-codes/${id}/default`, { method: "POST", token, body: { side } });
}

export function getVatReport(token: string, from: string, to: string) {
  return apiFetch<VatReport>(`/finance/reports/vat?date_from=${from}&date_to=${to}`, { token });
}

export function invalidateTaxData(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: TAX_KEYS.codes });
}
