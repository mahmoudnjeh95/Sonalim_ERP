import { apiFetch } from "../../../lib/api";

export type PickListStatus = "open" | "picking" | "picked" | "shipped" | "cancelled";
export type ShipmentStatus = "packed" | "shipped";

export interface PickList {
  id: string;
  number: string;
  source_type: string;
  source_id: string;
  partner_id: string | null;
  location_id: string;
  status: PickListStatus;
  created_at: string;
  picked_at: string | null;
  cancelled_at: string | null;
}

export interface PickListLine {
  id: string;
  pick_list_id: string;
  product_id: string;
  quantity_requested: number;
  // null until someone records a pick -- 0 is a real "nothing picked".
  quantity_picked: number | null;
  picked_by: string | null;
  picked_at: string | null;
}

export interface Shipment {
  id: string;
  number: string;
  pick_list_id: string;
  status: ShipmentStatus;
  package_count: number;
  total_weight_kg: number | null;
  carrier: string | null;
  tracking_reference: string | null;
  packed_by: string;
  packed_at: string;
  shipped_by: string | null;
  shipped_at: string | null;
}

export interface PickListDetail extends PickList {
  lines: PickListLine[];
  shipment: Shipment | null;
}

export const PICK_LISTS_QUERY_KEY = ["warehouse", "pickLists"] as const;
export const SHIPMENTS_QUERY_KEY = ["warehouse", "shipments"] as const;

export function pickListQueryKey(id: string) {
  return ["warehouse", "pickLists", id] as const;
}

export function listPickLists(token: string) {
  return apiFetch<PickList[]>("/warehouse/pick-lists", { token });
}

export function getPickList(token: string, pickListId: string) {
  return apiFetch<PickListDetail>(`/warehouse/pick-lists/${pickListId}`, { token });
}

export function submitPick(token: string, pickListId: string, lineId: string, quantityPicked: number) {
  return apiFetch<PickListLine>(`/warehouse/pick-lists/${pickListId}/lines/${lineId}/pick`, {
    method: "POST",
    token,
    body: { quantity_picked: quantityPicked },
  });
}

export function completePicking(token: string, pickListId: string) {
  return apiFetch<PickList>(`/warehouse/pick-lists/${pickListId}/complete`, { method: "POST", token });
}

export function cancelPickList(token: string, pickListId: string) {
  return apiFetch<PickList>(`/warehouse/pick-lists/${pickListId}/cancel`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}

export interface PackInput {
  package_count: number;
  total_weight_kg?: number | null;
  carrier?: string | null;
  tracking_reference?: string | null;
}

export function packPickList(token: string, pickListId: string, input: PackInput) {
  return apiFetch<Shipment>(`/warehouse/pick-lists/${pickListId}/pack`, { method: "POST", token, body: input });
}

export function listShipments(token: string) {
  return apiFetch<Shipment[]>("/warehouse/shipments", { token });
}

export function updateShipment(token: string, shipmentId: string, input: Partial<PackInput>) {
  return apiFetch<Shipment>(`/warehouse/shipments/${shipmentId}`, { method: "PATCH", token, body: input });
}

export function shipShipment(token: string, shipmentId: string) {
  return apiFetch<Shipment>(`/warehouse/shipments/${shipmentId}/ship`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}
