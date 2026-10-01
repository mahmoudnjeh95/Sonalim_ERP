import { PackageSearch } from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";

/**
 * Placeholder for parts requests. Task F7 replaces this with the
 * request/approve/reject workflow built on `usePartRequests`,
 * `usePartRequestAvailability`, `useApprovePartRequest` and `useRejectPartRequest`.
 */
export function PartsTab() {
  const { t } = useI18n();
  return (
    <Card>
      <CardContent>
        <EmptyState
          icon={<PackageSearch className="h-5 w-5" />}
          title={t("maintenance.parts.comingSoon.title")}
          description={t("maintenance.parts.comingSoon.description")}
        />
      </CardContent>
    </Card>
  );
}
