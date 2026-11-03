import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import type { PresenceStatus } from "../presenceApi";

const VARIANT: Record<PresenceStatus, BadgeProps["variant"]> = {
  present: "success", late: "warning", absent: "destructive", leave: "primary", holiday: "accent",
  rest: "default", sick: "warning", mission: "primary", suspended: "destructive",
};

export const PRESENCE_STATUS_LABEL: Record<PresenceStatus, TranslationKey> = {
  present: "hr.presenceStatus.present", absent: "hr.presenceStatus.absent", late: "hr.presenceStatus.late",
  leave: "hr.presenceStatus.leave", holiday: "hr.presenceStatus.holiday", rest: "hr.presenceStatus.rest",
  sick: "hr.presenceStatus.sick", mission: "hr.presenceStatus.mission", suspended: "hr.presenceStatus.suspended",
};

export const WEEKDAY_KEYS: TranslationKey[] = [
  "hr.weekday.0", "hr.weekday.1", "hr.weekday.2", "hr.weekday.3", "hr.weekday.4", "hr.weekday.5", "hr.weekday.6",
];
export const WEEKDAY_SHORT_KEYS: TranslationKey[] = [
  "hr.weekdayShort.0", "hr.weekdayShort.1", "hr.weekdayShort.2", "hr.weekdayShort.3", "hr.weekdayShort.4", "hr.weekdayShort.5", "hr.weekdayShort.6",
];

export function PresenceStatusBadge({ status }: { status: PresenceStatus }) {
  const { t } = useI18n();
  return (
    <Badge variant={VARIANT[status]} dot>
      {t(PRESENCE_STATUS_LABEL[status])}
    </Badge>
  );
}
