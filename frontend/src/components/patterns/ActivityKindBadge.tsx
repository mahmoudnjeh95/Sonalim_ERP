import { useI18n } from "../../lib/i18n";
import { Badge, type BadgeProps } from "../ui/badge";

type ActivityKind = "comment" | "task" | "call" | "meeting";

const KIND_VARIANT: Record<ActivityKind, BadgeProps["variant"]> = {
  comment: "default",
  task: "warning",
  call: "success",
  meeting: "accent",
};

// activity "kind" (comment/task/call/meeting) is a type classifier, not a
// status, so it deliberately reads its labels from crm.activity.kind.* rather
// than stretching the shared status.* namespace StatusBadge uses.
export function ActivityKindBadge({ kind }: { kind: string }) {
  const { t } = useI18n();
  const variant = KIND_VARIANT[kind as ActivityKind] ?? "default";
  const label = KIND_VARIANT[kind as ActivityKind] ? t(`crm.activity.kind.${kind}` as Parameters<typeof t>[0]) : kind;
  return (
    <Badge variant={variant} dot>
      {label}
    </Badge>
  );
}
