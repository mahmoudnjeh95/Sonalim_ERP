import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { RUN_TYPES, useCreateRun, usePayrollEmployees, type RunType } from "../api";
import { monthInputValue, parseMonthInput, periodParam } from "../format";

/** Creates a run (creation only: a run's label and off-cycle employees are edited on its own page). */
export function RunDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const create = useCreateRun();
  const [month, setMonth] = useState(() => monthInputValue(periodParam(new Date())));
  const [runType, setRunType] = useState<RunType>("regular");
  const [label, setLabel] = useState("");
  const [employeeIds, setEmployeeIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const period = parseMonthInput(month);
  const offCycle = runType === "off_cycle";
  const employees = usePayrollEmployees(offCycle ? period : "");

  // Every opening starts from a blank form on the current month.
  useEffect(() => {
    if (!open) return;
    setMonth(monthInputValue(periodParam(new Date())));
    setRunType("regular");
    setLabel("");
    setEmployeeIds([]);
    setSearch("");
    setFormError(null);
  }, [open]);

  const changeMonth = (value: string) => {
    setMonth(value);
    // Who is on the payroll depends on the month: a pick from another month may not apply.
    setEmployeeIds([]);
  };

  const toggleEmployee = (id: string, checked: boolean) =>
    setEmployeeIds((current) => (checked ? [...current, id] : current.filter((value) => value !== id)));

  const needle = search.trim().toLowerCase();
  const visibleEmployees = (employees.data ?? []).filter(
    (employee) => !needle || employee.full_name.toLowerCase().includes(needle) || employee.employee_no.toLowerCase().includes(needle),
  );

  const submit = () => {
    setFormError(null);
    create.mutate(
      {
        period,
        run_type: runType,
        label: label.trim() || null,
        employee_ids: offCycle && employeeIds.length > 0 ? employeeIds : null,
      },
      {
        onSuccess: (run) => {
          toast.success(t("payroll.runDialog.created"));
          onOpenChange(false);
          navigate(`/payroll/runs/${run.id}`);
        },
        // DUPLICATE_RUN / RUN_INVALID arrive in the user's language: keep them next to the form.
        onError: (error) => setFormError(error instanceof ApiError ? error.message : t("payroll.runDialog.error")),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("payroll.runDialog.title")}</DialogTitle>
          <DialogDescription>{t("payroll.runDialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="run-period">{t("payroll.runDialog.period")}</Label>
              <Input id="run-period" type="month" value={month} onChange={(event) => changeMonth(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="run-type">{t("payroll.runDialog.type")}</Label>
              <Select id="run-type" value={runType} onChange={(event) => setRunType(event.target.value as RunType)}>
                {RUN_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {t(`payroll.runs.type.${value}` as const)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="run-label">{t("payroll.runDialog.label")}</Label>
            <Input
              id="run-label"
              value={label}
              placeholder={t("payroll.runDialog.labelPlaceholder")}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          {offCycle && (
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor="run-employee-search">{t("payroll.runDialog.employees")}</Label>
                {employeeIds.length > 0 && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {employeeIds.length} {t("payroll.runDialog.selected")}
                  </span>
                )}
              </div>
              {!period ? (
                <p className="text-sm text-muted-foreground">{t("payroll.runDialog.pickPeriod")}</p>
              ) : (
                <>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="run-employee-search"
                      value={search}
                      placeholder={t("payroll.runDialog.searchEmployees")}
                      onChange={(event) => setSearch(event.target.value)}
                      className="pl-8"
                    />
                  </div>
                  <div className="max-h-48 overflow-y-auto rounded-md border border-border">
                    {employees.isLoading ? (
                      <div className="space-y-2 p-2">
                        {[0, 1, 2].map((index) => (
                          <Skeleton key={index} className="h-5 w-full" />
                        ))}
                      </div>
                    ) : visibleEmployees.length === 0 ? (
                      <p className="p-3 text-sm text-muted-foreground">{t("payroll.runDialog.noEmployees")}</p>
                    ) : (
                      <ul className="divide-y divide-border">
                        {visibleEmployees.map((employee) => (
                          <li key={employee.employee_id}>
                            <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted">
                              <Checkbox
                                checked={employeeIds.includes(employee.employee_id)}
                                onCheckedChange={(checked) => toggleEmployee(employee.employee_id, checked === true)}
                              />
                              <span className="truncate">{employee.full_name}</span>
                              <span className="ml-auto text-xs text-muted-foreground">{employee.employee_no}</span>
                            </label>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{t("payroll.runDialog.employeesHint")}</p>
                </>
              )}
            </div>
          )}
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={submit} disabled={!period || create.isPending}>
              {create.isPending ? t("common.saving") : t("common.create")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
