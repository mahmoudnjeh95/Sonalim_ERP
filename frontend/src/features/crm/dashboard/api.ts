import { apiFetch } from "../../../lib/api";

export interface StageBucket {
  count: number;
  amount: number;
}

export interface CountAmount {
  count: number;
  amount: number;
}

export interface RecentActivity {
  id: string;
  kind: "comment" | "task" | "call";
  subject_type: "lead" | "partner" | "opportunity";
  subject_id: string;
  note: string;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface CrmDashboard {
  won_amount: number;
  pipeline_by_stage: Record<string, StageBucket>;
  forecast: CountAmount;
  forecast_weighted: CountAmount;
  due_this_week: CountAmount;
  overdue: CountAmount;
  opportunities_by_month: {
    current_year: number;
    previous_year: number;
    current: number[];
    previous: number[];
  };
  activities_by_kind: Record<string, number>;
  recent_activities: RecentActivity[];
  leads_by_status: Record<string, number>;
  partners_by_status: Record<string, number>;
}

export function getCrmDashboard(token: string) {
  return apiFetch<CrmDashboard>("/crm/dashboard", { token });
}
