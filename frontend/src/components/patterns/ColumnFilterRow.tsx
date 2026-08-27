import { Input } from "../ui/input";
import { TableHead, TableRow } from "../ui/table";
import { useI18n } from "../../lib/i18n";

export type FilterCell =
  | { type: "blank" }
  | { type: "text"; placeholder: string; value: string; onChange: (value: string) => void }
  | {
      type: "range";
      min: string;
      max: string;
      onMinChange: (value: string) => void;
      onMaxChange: (value: string) => void;
    };

const inputClassName = "h-7 w-full text-xs font-normal normal-case tracking-normal";

export function ColumnFilterRow({ cells }: { cells: FilterCell[] }) {
  const { t } = useI18n();
  return (
    <TableRow className="hover:bg-transparent">
      {cells.map((cell, i) => (
        <TableHead key={i} className="py-1.5">
          {cell.type === "text" && (
            <Input
              value={cell.value}
              onChange={(event) => cell.onChange(event.target.value)}
              placeholder={cell.placeholder}
              className={inputClassName}
            />
          )}
          {cell.type === "range" && (
            <div className="flex items-center gap-1">
              <Input
                type="number"
                step="any"
                value={cell.min}
                onChange={(event) => cell.onMinChange(event.target.value)}
                placeholder={t("common.min")}
                className={inputClassName}
              />
              <Input
                type="number"
                step="any"
                value={cell.max}
                onChange={(event) => cell.onMaxChange(event.target.value)}
                placeholder={t("common.max")}
                className={inputClassName}
              />
            </div>
          )}
        </TableHead>
      ))}
    </TableRow>
  );
}
