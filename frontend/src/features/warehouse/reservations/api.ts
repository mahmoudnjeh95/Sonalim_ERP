import { apiFetch } from "../../../lib/api";

export type ReservationStatus = "active" | "released" | "expired";

export interface StockReservation {
  id: string;
  product_id: string;
  location_id: string;
  reference: string;
  quantity: number;
  quantity_open: number;
  status: ReservationStatus;
  expires_at: string | null;
  created_by: string | null;
  created_at: string;
  closed_at: string | null;
}

export const RESERVATIONS_QUERY_KEY = ["warehouse", "reservations"] as const;

export function listReservations(token: string) {
  return apiFetch<StockReservation[]>("/warehouse/reservations", { token });
}

export function releaseReservation(token: string, reservationId: string) {
  return apiFetch<StockReservation>(`/warehouse/reservations/${reservationId}/release`, { method: "POST", token });
}

export function updateReservationExpiry(token: string, reservationId: string, expiresAt: string | null) {
  return apiFetch<StockReservation>(`/warehouse/reservations/${reservationId}`, {
    method: "PATCH",
    token,
    body: expiresAt ? { expires_at: expiresAt } : { clear_expiry: true },
  });
}
