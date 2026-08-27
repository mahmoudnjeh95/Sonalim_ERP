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
  | "prospecting"
  | "qualification"
  | "proposal"
  | "negotiation"
  | "won"
  | "lost";

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
  prospecting: "default",
  qualification: "primary",
  proposal: "accent",
  negotiation: "warning",
  won: "success",
  lost: "destructive",
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
