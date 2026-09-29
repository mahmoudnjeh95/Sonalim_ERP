import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { createDepartment, hrKeys, listDepartments, listEmployees, updateDepartment, type Department, type DepartmentInput } from "../api";
import { FormField } from "../FormField";
import { HrListTable } from "../HrListTable";

export function DepartmentsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; department: Department | null }>({ open: false, department: null });
  const { data: departments = [], isLoading } = useQuery({ queryKey: hrKeys.departments, queryFn: () => listDepartments(session!.token) });
  const filters = useColumnFilters<Department>([
    { key: "code", kind: "text", getValue: (row) => row.code },
    { key: "name", kind: "text", getValue: (row) => row.name },
    { key: "manager", kind: "text", getValue: (row) => row.manager_name },
    { key: "count", kind: "range", getValue: (row) => row.employee_count },
  ]);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });
  const columns: ColumnDef<Department>[] = [
    { key: "code", header: t("hr.org.code"), defaultWidth: 120, cell: (row) => <span className="font-medium">{row.code}</span>, filterCell: text("code", t("hr.org.code")), sortValue: (row) => row.code },
    { key: "name", header: t("hr.org.name"), defaultWidth: 220, cell: (row) => row.name, filterCell: text("name", t("hr.org.name")), sortValue: (row) => row.name },
    { key: "manager", header: t("hr.org.manager"), defaultWidth: 200, cell: (row) => row.manager_name ?? "—", filterCell: text("manager", t("hr.org.manager")), sortValue: (row) => row.manager_name },
    {
      key: "count",
      header: t("hr.org.employees"),
      defaultWidth: 130,
      cell: (row) => row.employee_count,
      filterCell: {
        type: "range",
        min: filters.range.count?.min ?? "",
        max: filters.range.count?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("count", "min", value),
        onMaxChange: (value) => filters.setRangeValue("count", "max", value),
      },
      sortValue: (row) => row.employee_count,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_departments") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, department: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.org.tab.departments")}</CardTitle>
        {hasPermission("hr.manage_departments") && (
          <Button onClick={() => setDialog({ open: true, department: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.org.department.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrListTable
          tableKey="hr.organisation.departments"
          columns={columns}
          rows={filters.apply(departments)}
          rowKey={(row) => row.id}
          loading={isLoading}
          loadingVariant="loader"
          bordered={false}
          emptyIcon={<Building2 className="h-5 w-5" />}
          emptyTitle={t("hr.org.department.empty.title")}
          emptyDescription={t("hr.org.department.empty.description")}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <DepartmentDialog open={dialog.open} department={dialog.department} onOpenChange={(open) => setDialog((current) => ({ ...current, open }))} />
    </Card>
  );
}

function DepartmentDialog({ open, department, onOpenChange }: { open: boolean; department: Department | null; onOpenChange: (open: boolean) => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", name: "", manager_employee_id: "" });
  const [fieldError, setFieldError] = useState<string | null>(null);
  const employees = useQuery({ queryKey: hrKeys.employees, queryFn: () => listEmployees(session!.token), enabled: open && hasPermission("hr.view_employees") });

  useEffect(() => {
    if (open) {
      setForm({ code: department?.code ?? "", name: department?.name ?? "", manager_employee_id: department?.manager_employee_id ?? "" });
      setFieldError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, department?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: DepartmentInput = { code: form.code.trim(), name: form.name.trim(), manager_employee_id: emptyOrNull(form.manager_employee_id) };
      return department ? updateDepartment(session!.token, department.id, input) : createDepartment(session!.token, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.departments });
      toast.success(t("hr.org.saved"));
      onOpenChange(false);
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : t("hr.org.error");
      setFieldError(message);
      toast.error(t("hr.org.error"));
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(department ? "hr.org.department.editTitle" : "hr.org.department.createTitle")}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <FormField id="department-code" label={t("hr.org.code")} hint={t("hr.org.department.codeHint")} error={fieldError ?? undefined}>
            <Input id="department-code" required value={form.code} onChange={(event) => { setForm({ ...form, code: event.target.value }); setFieldError(null); }} />
          </FormField>
          <FormField id="department-name" label={t("hr.org.name")}>
            <Input id="department-name" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </FormField>
          <FormField id="department-manager" label={t("hr.org.manager")}>
            <Select id="department-manager" value={form.manager_employee_id} onChange={(event) => setForm({ ...form, manager_employee_id: event.target.value })}>
              <option value="">{t("hr.org.noManager")}</option>
              {(employees.data ?? []).filter((row) => row.status !== "terminated").map((row) => (
                <option key={row.id} value={row.id}>
                  {row.employee_no} — {row.full_name}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function emptyOrNull(value: string): string | null {
  return value === "" ? null : value;
}
