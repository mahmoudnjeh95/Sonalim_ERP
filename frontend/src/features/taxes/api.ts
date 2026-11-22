import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export type TaxSide = "sales" | "purchases";
export type TaxScope = TaxSide | "both";

export interface TaxCode {
  id: string;
  code: string;
  name_fr: string;
  name_en: string;
  rate: number;
  scope: TaxScope;
  exempt: boolean;
  legal_mention: string | null;
  active: boolean;
}

export interface TaxCodeInput {
  code?: string;
  name_fr: string;
  name_en?: string | null;
  rate: number;
  scope: TaxScope;
  exempt: boolean;
  legal_mention?: string | null;
  active?: boolean;
}

export interface TaxAssignment {
  sales_tax_code_id: string | null;
  purchases_tax_code_id: string | null;
}

export type ResolvedTaxes = Record<string, { tax_code: string | null; rate: number }>;

export const TAX_KEYS = {
  codes: (includeInactive: boolean) => ["core", "tax-codes", includeInactive] as const,
  all: ["core", "tax-codes"] as const,
  product: (id: string) => ["core", "tax-codes", "product", id] as const,
  partner: (id: string) => ["core", "tax-codes", "partner", id] as const,
  resolve: (side: TaxSide, partnerId: string, productIds: string[], defaultRate: number) =>
    ["core", "tax-codes", "resolve", side, partnerId, productIds.join(","), defaultRate] as const,
};

const BASE = "/core/tax-codes";

export const listTaxCodes = (token: string, includeInactive = false) =>
  apiFetch<TaxCode[]>(`${BASE}${includeInactive ? "?include_inactive=true" : ""}`, { token });
export const createTaxCode = (token: string, body: TaxCodeInput) => apiFetch<TaxCode>(BASE, { method: "POST", token, body });
export const updateTaxCode = (token: string, id: string, body: Partial<TaxCodeInput>) =>
  apiFetch<TaxCode>(`${BASE}/${id}`, { method: "PATCH", token, body });
export const getProductTaxCodes = (token: string, productId: string) => apiFetch<TaxAssignment>(`${BASE}/products/${productId}`, { token });
export const setProductTaxCodes = (token: string, productId: string, body: Partial<TaxAssignment>) =>
  apiFetch<TaxAssignment>(`${BASE}/products/${productId}`, { method: "PUT", token, body });
export const getPartnerTaxCodes = (token: string, partnerId: string) => apiFetch<TaxAssignment>(`${BASE}/partners/${partnerId}`, { token });
export const setPartnerTaxCodes = (token: string, partnerId: string, body: Partial<TaxAssignment>) =>
  apiFetch<TaxAssignment>(`${BASE}/partners/${partnerId}`, { method: "PUT", token, body });

export function resolveTaxes(token: string, side: TaxSide, partnerId: string, productIds: string[], defaultRate: number) {
  const params = new URLSearchParams({ side, default_rate: String(defaultRate) });
  if (partnerId) params.set("partner_id", partnerId);
  productIds.forEach((id) => params.append("product_id", id));
  return apiFetch<ResolvedTaxes>(`${BASE}/resolve?${params.toString()}`, { token });
}

/** The active codes that apply to one side (sales or purchases). */
export function useTaxCodes(side?: TaxSide) {
  const { session } = useAuth();
  const query = useQuery({ queryKey: TAX_KEYS.codes(false), queryFn: () => listTaxCodes(session!.token), staleTime: 60_000 });
  const codes = (query.data ?? []).filter((code) => !side || code.scope === "both" || code.scope === side);
  return { ...query, codes };
}

/** What each product's new line would be taxed at for this partner when the user names no code. */
export function useResolvedTaxes(side: TaxSide, partnerId: string, productIds: string[], defaultRate: number) {
  const { session } = useAuth();
  const ids = [...new Set(productIds.filter(Boolean))].sort();
  return useQuery({
    queryKey: TAX_KEYS.resolve(side, partnerId, ids, defaultRate),
    queryFn: () => resolveTaxes(session!.token, side, partnerId, ids, defaultRate),
    staleTime: 30_000,
  });
}

export function taxCodeLabel(code: Pick<TaxCode, "code" | "rate">): string {
  return `${code.code} · ${Number(code.rate)} %`;
}
