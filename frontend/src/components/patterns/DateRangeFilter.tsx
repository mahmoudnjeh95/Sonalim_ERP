import { RotateCcw } from "lucide-react";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { useI18n } from "../../lib/i18n";

/**
 * A from/to date pair with a reset back to the caller's default window.
 * The default itself (a rolling "last N periods") is computed by the caller —
 * this component only ever holds an override on top of it.
 */
export function DateRangeFilter({
  from,
  to,
  onChange,
  onReset,
  isDefault,
}: {
  from: string;
  to: string;
  onChange: (range: { from: string; to: string }) => void;
  onReset: () => void;
  isDefault: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <label className="flex items-center gap-1.5 text-muted-foreground">
        {t("common.dateFrom")}
        <Input type="date" value={from} max={to} onChange={(e) => onChange({ from: e.target.value, to })} className="h-8 w-auto" />
      </label>
      <label className="flex items-center gap-1.5 text-muted-foreground">
        {t("common.dateTo")}
        <Input type="date" value={to} min={from} onChange={(e) => onChange({ from, to: e.target.value })} className="h-8 w-auto" />
      </label>
      {!isDefault && (
        <Button type="button" variant="ghost" size="sm" onClick={onReset} className="h-8 gap-1 px-2 text-xs">
          <RotateCcw className="h-3.5 w-3.5" />
          {t("common.resetRange")}
        </Button>
      )}
    </div>
  );
}
