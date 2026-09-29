import { Lock } from "lucide-react";
import { useI18n } from "../../lib/i18n";

/** What a caller without hr.view_sensitive sees in place of a hidden value. */
export function Masked() {
  const { t } = useI18n();
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground" title={t("hr.sensitive.hidden")}>
      <Lock className="h-3.5 w-3.5" />
      ••••
    </span>
  );
}
