import { useEffect, useState, type KeyboardEvent } from "react";
import { Check, Search } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Skeleton } from "../../../components/ui/skeleton";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { usePayrollEmployees } from "../api";

/**
 * Picks one employee on the payroll in `period` ("YYYY-MM-01"). GET /payroll/employees has no
 * search parameter, so the month's list is fetched once (cached per period) and filtered here by
 * name or number — fine at a plant's size (plan, "Decisions / gaps found" #2). The list renders
 * inline rather than in a popover so it scrolls normally inside a dialog.
 */
export function EmployeeSelect({
  id,
  period,
  value,
  onChange,
  invalid,
}: {
  id?: string;
  period: string;
  value: string;
  onChange: (employeeId: string) => void;
  invalid?: boolean;
}) {
  const { t } = useI18n();
  const employees = usePayrollEmployees(period);
  const [search, setSearch] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const list = employees.data ?? [];
  const selected = list.find((employee) => employee.employee_id === value);

  // Who is on the payroll depends on the month: a pick that is not on the new month's list is dropped.
  useEffect(() => {
    if (value && employees.isSuccess && !employees.data.some((employee) => employee.employee_id === value)) onChange("");
  }, [value, employees.isSuccess, employees.data, onChange]);

  if (!period) {
    return <p className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">{t("payroll.employeeSelect.pickPeriod")}</p>;
  }

  if (selected && !browsing) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/30 py-1 pl-3 pr-1">
        <span className="min-w-0 truncate text-sm">
          <span className="font-medium">{selected.full_name}</span>
          <span className="ml-1.5 text-xs text-muted-foreground">{selected.employee_no}</span>
        </span>
        <Button
          id={id}
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            setSearch("");
            setBrowsing(true);
          }}
        >
          {t("payroll.employeeSelect.change")}
        </Button>
      </div>
    );
  }

  const needle = search.trim().toLowerCase();
  const matches = list.filter(
    (employee) => !needle || employee.full_name.toLowerCase().includes(needle) || employee.employee_no.toLowerCase().includes(needle),
  );

  const pick = (employeeId: string) => {
    onChange(employeeId);
    setBrowsing(false);
    setSearch("");
  };

  // Enter takes the first match instead of submitting the surrounding form.
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (matches.length > 0) pick(matches[0].employee_id);
  };

  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={id}
          autoFocus={browsing}
          value={search}
          placeholder={t("payroll.employeeSelect.placeholder")}
          onChange={(event) => setSearch(event.target.value)}
          onKeyDown={onKeyDown}
          aria-invalid={invalid || undefined}
          className={cn("pl-8", invalid && "border-destructive focus-visible:ring-destructive")}
        />
      </div>
      <div className="max-h-44 overflow-y-auto rounded-md border border-border">
        {employees.isLoading ? (
          <div className="space-y-2 p-2">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-5 w-full" />
            ))}
          </div>
        ) : matches.length === 0 ? (
          <p className="p-3 text-sm text-muted-foreground">{t("payroll.employeeSelect.noMatch")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {matches.map((employee) => {
              const active = employee.employee_id === value;
              return (
                <li key={employee.employee_id}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => pick(employee.employee_id)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none",
                      active && "bg-primary/5",
                    )}
                  >
                    <span className="truncate">{employee.full_name}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{employee.employee_no}</span>
                    {active && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
