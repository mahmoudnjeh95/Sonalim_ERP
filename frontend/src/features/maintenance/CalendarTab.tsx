import { CalendarDays } from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";

/**
 * Placeholder for the maintenance calendar (default tab). Task F6 replaces
 * this with the month/week view combining `useCalendar` jobs and projected
 * program occurrences.
 */
export function CalendarTab() {
  const { t } = useI18n();
  return (
    <Card>
      <CardContent>
        <EmptyState
          icon={<CalendarDays className="h-5 w-5" />}
          title={t("maintenance.calendar.comingSoon.title")}
          description={t("maintenance.calendar.comingSoon.description")}
        />
      </CardContent>
    </Card>
  );
}
