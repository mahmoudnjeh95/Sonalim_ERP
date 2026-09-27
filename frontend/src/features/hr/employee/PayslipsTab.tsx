import { Receipt } from "lucide-react";
import { useI18n } from "../../../lib/i18n";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Card, CardContent } from "../../../components/ui/card";

export function PayslipsTab() {
  const { t } = useI18n();
  return (
    <Card>
      <CardContent className="p-0">
        <EmptyState icon={<Receipt className="h-5 w-5" />} title={t("hr.file.payslips.title")} description={t("hr.file.payslips.description")} />
      </CardContent>
    </Card>
  );
}
