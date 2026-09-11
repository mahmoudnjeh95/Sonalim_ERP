import type { ReactNode } from "react";
import { useI18n } from "../../lib/i18n";
import { Button } from "../ui/button";

/** Appears once at least one row is selected; hidden otherwise. */
export function BulkActionBar({ count, onClear, children }: { count: number; onClear: () => void; children: ReactNode }) {
  const { t } = useI18n();
  if (count === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
      <span className="text-sm font-medium">
        {count} {t("common.selected")}
      </span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
      <Button variant="ghost" size="sm" className="ml-auto" onClick={onClear}>
        {t("common.clearSelection")}
      </Button>
    </div>
  );
}
