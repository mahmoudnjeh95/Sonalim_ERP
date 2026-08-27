import { Columns3 } from "lucide-react";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { Label } from "../ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import { useI18n } from "../../lib/i18n";
import type { ColumnDef } from "../../lib/useTableColumns";

export function ColumnVisibilityMenu<Row>({
  columns,
  isVisible,
  onToggle,
  onReset,
}: {
  columns: ColumnDef<Row>[];
  isVisible: (key: string) => boolean;
  onToggle: (key: string) => void;
  onReset: () => void;
}) {
  const { t } = useI18n();
  const toggleable = columns.filter((column) => !column.alwaysVisible);
  if (toggleable.length === 0) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <Columns3 className="h-3.5 w-3.5" />
          {t("table.columns.button")}
        </Button>
      </PopoverTrigger>
      <PopoverContent>
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase text-muted-foreground">{t("table.columns.title")}</p>
          <div className="space-y-1.5">
            {toggleable.map((column) => (
              <div key={column.key} className="flex items-center gap-2 text-sm">
                <Checkbox
                  id={`col-vis-${column.key}`}
                  checked={isVisible(column.key)}
                  onCheckedChange={() => onToggle(column.key)}
                />
                <Label htmlFor={`col-vis-${column.key}`} className="cursor-pointer font-normal">
                  {column.header}
                </Label>
              </div>
            ))}
          </div>
          <Button variant="ghost" size="sm" className="w-full" onClick={onReset}>
            {t("table.columns.reset")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
