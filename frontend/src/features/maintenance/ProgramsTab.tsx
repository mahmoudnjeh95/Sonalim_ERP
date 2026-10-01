import { Repeat } from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";

/**
 * Placeholder for preventive-maintenance programs. Task F6 replaces this
 * with the list/editor built on `usePrograms`, `useCreateProgram`,
 * `useUpdateProgram` and `useRunDuePrograms`.
 */
export function ProgramsTab() {
  const { t } = useI18n();
  return (
    <Card>
      <CardContent>
        <EmptyState
          icon={<Repeat className="h-5 w-5" />}
          title={t("maintenance.programs.comingSoon.title")}
          description={t("maintenance.programs.comingSoon.description")}
        />
      </CardContent>
    </Card>
  );
}
