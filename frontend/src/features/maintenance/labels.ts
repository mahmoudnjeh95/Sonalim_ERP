import { CircleDot, Droplet, Eye, Gauge, RefreshCw, Sparkles, Wrench, type LucideIcon } from "lucide-react";
import type { BadgeProps } from "../../components/ui/badge";
import type { TranslationKey } from "../../lib/i18n";
import type { CheckAction, JobStatus, Outcome } from "./api";

/**
 * Display metadata (i18n key, badge colour, icon where relevant) for the
 * maintenance workflow's small enums. Centralised here so every tab (jobs,
 * job page, calendar, programs, wizard, review) renders the same status the
 * same way — later tasks (F3-F7) import from this file rather than
 * re-deriving their own labels/colours.
 */

export const JOB_STATUS_LABEL_KEY: Record<JobStatus, TranslationKey> = {
  planned: "maintenance.jobStatus.planned",
  assigned: "maintenance.jobStatus.assigned",
  in_progress: "maintenance.jobStatus.in_progress",
  submitted: "maintenance.jobStatus.submitted",
  rework: "maintenance.jobStatus.rework",
  closed: "maintenance.jobStatus.closed",
  cancelled: "maintenance.jobStatus.cancelled",
};

export const JOB_STATUS_BADGE_VARIANT: Record<JobStatus, BadgeProps["variant"]> = {
  planned: "outline",
  assigned: "primary",
  in_progress: "accent",
  submitted: "warning",
  rework: "destructive",
  closed: "success",
  cancelled: "default",
};

export const CHECK_ACTION_LABEL_KEY: Record<CheckAction, TranslationKey> = {
  inspect: "maintenance.checkAction.inspect",
  lubricate: "maintenance.checkAction.lubricate",
  tighten: "maintenance.checkAction.tighten",
  clean: "maintenance.checkAction.clean",
  replace: "maintenance.checkAction.replace",
  measure: "maintenance.checkAction.measure",
  other: "maintenance.checkAction.other",
};

export const CHECK_ACTION_ICON: Record<CheckAction, LucideIcon> = {
  inspect: Eye,
  lubricate: Droplet,
  tighten: Wrench,
  clean: Sparkles,
  replace: RefreshCw,
  measure: Gauge,
  other: CircleDot,
};

export const OUTCOME_LABEL_KEY: Record<Outcome, TranslationKey> = {
  ok: "maintenance.outcome.ok",
  issue: "maintenance.outcome.issue",
  not_done: "maintenance.outcome.not_done",
};

export const OUTCOME_BADGE_VARIANT: Record<Outcome, BadgeProps["variant"]> = {
  ok: "success",
  issue: "destructive",
  not_done: "default",
};
