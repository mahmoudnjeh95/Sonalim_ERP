import { apiFetch } from "../../lib/api";

export interface Currency {
  code: string;
  name: string;
  decimal_places: number;
}

export interface CreateCurrencyInput {
  code: string;
  name: string;
  decimal_places?: number;
}

export interface TodayRate {
  currency_code: string;
  rate_to_base: number | null;
  effective_date: string | null;
  source: string | null;
  is_today: boolean;
}

export interface RecordExchangeRateInput {
  currency_code: string;
  rate_to_base: number;
  effective_date: string;
  source?: string;
}

export function listCurrencies(token: string) {
  return apiFetch<Currency[]>("/core/currencies", { token });
}

export function createCurrency(token: string, input: CreateCurrencyInput) {
  return apiFetch<Currency>("/core/currencies", { method: "POST", token, body: input });
}

export function getTodayRates(token: string) {
  return apiFetch<TodayRate[]>("/core/exchange-rates/today", { token });
}

export function recordExchangeRate(token: string, input: RecordExchangeRateInput) {
  return apiFetch<TodayRate>("/core/exchange-rates", { method: "POST", token, body: input });
}
