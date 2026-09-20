import { apiFetch } from "../../lib/api";
import { listWorkCenters, type WorkCenter } from "../production/api";

export type { WorkCenter };
export { listWorkCenters };

export type EquipmentStatus = "operational" | "down" | "maintenance";

/** The stages of a production line a machine can work at, in the order a line runs them. */
export const PRODUCTION_STAGES = ["versement", "extrusion", "conditionnement"] as const;
export type ProductionStage = (typeof PRODUCTION_STAGES)[number];

export interface Equipment {
  id: string;
  work_center_id: string;
  code: string;
  name: string;
  status: EquipmentStatus;
  /** null for a machine that works at none of the stages. */
  production_stage: ProductionStage | null;
}

export interface CreateEquipmentInput {
  work_center_id: string;
  code: string;
  name: string;
  production_stage?: ProductionStage | null;
}

export interface UpdateEquipmentInput {
  work_center_id?: string;
  code?: string;
  name?: string;
  /** null clears the stage; leaving it out keeps it. */
  production_stage?: ProductionStage | null;
}

export function listEquipment(token: string) {
  return apiFetch<Equipment[]>("/maintenance/equipment", { token });
}

export function createEquipment(token: string, input: CreateEquipmentInput) {
  return apiFetch<Equipment>("/maintenance/equipment", { method: "POST", token, body: input });
}

export function updateEquipment(token: string, equipmentId: string, input: UpdateEquipmentInput) {
  return apiFetch<Equipment>(`/maintenance/equipment/${equipmentId}`, { method: "PATCH", token, body: input });
}

export function setEquipmentStatus(token: string, equipmentId: string, status: EquipmentStatus) {
  return apiFetch<Equipment>(`/maintenance/equipment/${equipmentId}/status`, { method: "POST", token, body: { status } });
}
