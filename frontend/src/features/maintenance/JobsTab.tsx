import { ClipboardList } from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";

/**
 * Placeholder for the jobs list. Task F4 replaces this with the full table
 * (filters, status badges, links to the job page) built on `useJobs`.
 */
export function JobsTab() {
  const { t } = useI18n();
  return (
    <Card>
      <CardContent>
        <EmptyState
          icon={<ClipboardList className="h-5 w-5" />}
          title={t("maintenance.jobs.comingSoon.title")}
          description={t("maintenance.jobs.comingSoon.description")}
        />
      </CardContent>
    </Card>
  );
}
