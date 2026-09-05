import { type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "../ui/button";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "../ui/popover";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";

export interface RowAction {
  key: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  /** Renders in the destructive colour — cancelling an order, deleting a report. */
  tone?: "default" | "destructive";
}

/**
 * The actions on a table row, behind one button.
 *
 * A row of labelled buttons is readable right up to the point where the table
 * stops fitting the window, and then it is the reason the table stops fitting:
 * the actions column was the widest on the OF list and the buttons still spilled
 * out of it. Collapsing them costs one click and buys every other column the
 * room to show its content.
 *
 * The trigger stops propagation so it works inside a clickable row without also
 * opening whatever the row opens.
 */
export function RowActionsMenu({ actions, label }: { actions: RowAction[]; label?: string }) {
  const { t } = useI18n();
  if (actions.length === 0) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          aria-label={label ?? t("table.rowActions.label")}
          onClick={(event) => event.stopPropagation()}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-56 p-1.5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="space-y-0.5">
          {actions.map((action) => (
            <PopoverClose asChild key={action.key}>
              <button
                type="button"
                disabled={action.disabled}
                onClick={action.onSelect}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  "hover:bg-muted disabled:pointer-events-none disabled:opacity-50",
                  action.tone === "destructive" && "text-destructive hover:bg-destructive-soft",
                )}
              >
                {action.icon}
                {action.label}
              </button>
            </PopoverClose>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
