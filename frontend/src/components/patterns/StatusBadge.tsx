import { useI18n } from "../../lib/i18n";
import { Badge, type BadgeProps } from "../ui/badge";

type Status =
  | "draft"
  | "in_progress"
  | "active"
  | "confirmed"
  | "completed"
  | "issued"
  | "paid"
  | "archived"
  | "new"
  | "qualified"
  | "converted"
  | "disqualified"
  | "prospecting"
  | "qualification"
  | "proposal"
  | "negotiation"
  | "won"
  | "lost"
  // OF lifecycle (production rebuild)
  | "planned"
  | "ongoing"
  | "suspended"
  | "closed"
  | "cancelled"
  // Report and quality-report lifecycle
  | "submitted"
  | "validated"
  | "rejected"
  // Quality follow-up
  | "open"
  // Non-conformity
  | "raised"
  | "quarantined"
  | "dispositioned";

const STATUS_VARIANT: Record<Status, BadgeProps["variant"]> = {
  draft: "default",
  in_progress: "warning",
  active: "success",
  confirmed: "success",
  completed: "success",
  issued: "primary",
  paid: "success",
  archived: "outline",
  new: "default",
  qualified: "primary",
  converted: "success",
  disqualified: "destructive",
  prospecting: "default",
  qualification: "primary",
  proposal: "accent",
  negotiation: "warning",
  won: "success",
  lost: "destructive",
  // An OF is neutral while planned, warm while it runs, and green only once it
  // is closed — a cancelled order reads as a dead end, not a success.
  planned: "default",
  ongoing: "warning",
  suspended: "accent",
  closed: "success",
  cancelled: "destructive",
  // A report is only official once validated; a rejection needs to be loud
  // enough that nobody mistakes it for "done".
  submitted: "primary",
  validated: "success",
  rejected: "destructive",
  open: "warning",
  // Non-conformity: quarantined is deliberately alarming — that product is
  // sitting in a blocked location waiting for someone to decide its fate.
  raised: "warning",
  quarantined: "destructive",
  dispositioned: "primary",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const variant = STATUS_VARIANT[status as Status] ?? "default";
  const key = `status.${status}` as Parameters<typeof t>[0];
  const label = STATUS_VARIANT[status as Status] ? t(key) : status;
  return (
    <Badge variant={variant} dot>
      {label}
    </Badge>
  );
}

type Category = "raw_material" | "semi_finished" | "packaging_component" | "finished_good";

const CATEGORY_VARIANT: Record<Category, BadgeProps["variant"]> = {
  raw_material: "primary",
  semi_finished: "accent",
  packaging_component: "warning",
  finished_good: "success",
};

export function CategoryBadge({ category }: { category: string }) {
  const { t } = useI18n();
  const variant = CATEGORY_VARIANT[category as Category] ?? ("default" as const);
  const key = `production.classifications.category.${category}` as Parameters<typeof t>[0];
  const label = CATEGORY_VARIANT[category as Category] ? t(key) : category;
  return <Badge variant={variant}>{label}</Badge>;
}

type Priority = "low" | "medium" | "high";

const PRIORITY_VARIANT: Record<Priority, BadgeProps["variant"]> = {
  low: "outline",
  medium: "warning",
  high: "destructive",
};

/** Red/amber/gray so a scan of the board or table finds the urgent deals first. */
export function PriorityBadge({ priority }: { priority: string }) {
  const { t } = useI18n();
  const variant = PRIORITY_VARIANT[priority as Priority] ?? "default";
  const key = `priority.${priority}` as Parameters<typeof t>[0];
  const label = PRIORITY_VARIANT[priority as Priority] ? t(key) : priority;
  return (
    <Badge variant={variant} dot={priority === "high"}>
      {label}
    </Badge>
  );
}
