import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Tag } from "lucide-react";
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
import { createPosition, hrKeys, listDepartments, listPositions, updatePosition, type Position, type PositionInput } from "../api";
import { FormField } from "../FormField";
import { HrListTable } from "../HrListTable";

export function PositionsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; position: Position | null }>({ open: false, position: null });
  const { data: positions = [], isLoading } = useQuery({ queryKey: hrKeys.positions, queryFn: () => listPositions(session!.token) });
  const filters = useColumnFilters<Position>([
    { key: "code", kind: "text", getValue: (row) => row.code },
    { key: "title", kind: "text", getValue: (row) => row.title },
    { key: "department", kind: "text", getValue: (row) => row.department_name },
    { key: "headcount", kind: "range", getValue: (row) => row.headcount },
  ]);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });
  const columns: ColumnDef<Position>[] = [
    { key: "code", header: t("hr.org.code"), defaultWidth: 120, cell: (row) => <span className="font-medium">{row.code}</span>, filterCell: text("code", t("hr.org.code")), sortValue: (row) => row.code },
    { key: "title", header: t("hr.org.position.title"), defaultWidth: 240, cell: (row) => row.title, filterCell: text("title", t("hr.org.position.title")), sortValue: (row) => row.title },
    { key: "department", header: t("hr.field.department"), defaultWidth: 180, cell: (row) => row.department_name ?? "—", filterCell: text("department", t("hr.field.department")), sortValue: (row) => row.department_name },
    {
      key: "headcount",
      header: t("hr.org.position.headcount"),
      defaultWidth: 150,
      // The budget is a recorded figure; the cell states both numbers and judges nothing.
      cell: (row) => `${row.headcount}${row.headcount_budget !== null ? ` / ${row.headcount_budget}` : ""}`,
      filterCell: {
        type: "range",
        min: filters.range.headcount?.min ?? "",
        max: filters.range.headcount?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("headcount", "min", value),
        onMaxChange: (value) => filters.setRangeValue("headcount", "max", value),
      },
      sortValue: (row) => row.headcount,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_positions") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, position: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.org.tab.positions")}</CardTitle>
        {hasPermission("hr.manage_positions") && (
          <Button onClick={() => setDialog({ open: true, position: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.org.position.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrListTable
          tableKey="hr.organisation.positions"
          columns={columns}
          rows={filters.apply(positions)}
          rowKey={(row) => row.id}
          loading={isLoading}
          loadingVariant="loader"
          bordered={false}
          emptyIcon={<Tag className="h-5 w-5" />}
          emptyTitle={t("hr.org.position.empty.title")}
          emptyDescription={t("hr.org.position.empty.description")}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <PositionDialog open={dialog.open} position={dialog.position} onOpenChange={(open) => setDialog((current) => ({ ...current, open }))} />
    </Card>
  );
}

function PositionDialog({ open, position, onOpenChange }: { open: boolean; position: Position | null; onOpenChange: (open: boolean) => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", title: "", department_id: "", headcount_budget: "" });
  const departments = useQuery({ queryKey: hrKeys.departments, queryFn: () => listDepartments(session!.token), enabled: open && hasPermission("hr.view_departments") });

  useEffect(() => {
    if (open)
      setForm({
        code: position?.code ?? "",
        title: position?.title ?? "",
        department_id: position?.department_id ?? "",
        headcount_budget: position?.headcount_budget == null ? "" : String(position.headcount_budget),
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, position?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: PositionInput = {
        code: form.code.trim(),
        title: form.title.trim(),
        department_id: form.department_id === "" ? null : form.department_id,
        headcount_budget: form.headcount_budget.trim() === "" ? null : Number(form.headcount_budget),
      };
      return position ? updatePosition(session!.token, position.id, input) : createPosition(session!.token, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.positions });
      toast.success(t("hr.org.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.org.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(position ? "hr.org.position.editTitle" : "hr.org.position.createTitle")}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <div className="grid grid-cols-2 gap-3">
            <FormField id="position-code" label={t("hr.org.code")}>
              <Input id="position-code" required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} />
            </FormField>
            <FormField id="position-budget" label={t("hr.org.position.budget")}>
              <Input id="position-budget" type="number" min="0" step="1" value={form.headcount_budget} onChange={(event) => setForm({ ...form, headcount_budget: event.target.value })} />
            </FormField>
          </div>
          <FormField id="position-title" label={t("hr.org.position.title")}>
            <Input id="position-title" required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
          </FormField>
          <FormField id="position-department" label={t("hr.field.department")}>
            <Select id="position-department" value={form.department_id} onChange={(event) => setForm({ ...form, department_id: event.target.value })}>
              <option value="">{t("hr.form.noneOption")}</option>
              {(departments.data ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
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
