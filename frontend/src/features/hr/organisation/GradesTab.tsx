import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { createGrade, hrKeys, listGrades, updateGrade, type Grade, type GradeInput } from "../api";
import { formatDate, formatXof, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

export function GradesTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; grade: Grade | null }>({ open: false, grade: null });
  const { data: grades = [], isLoading } = useQuery({ queryKey: hrKeys.grades, queryFn: () => listGrades(session!.token) });
  const filters = useColumnFilters<Grade>([
    { key: "code", kind: "text", getValue: (row) => row.code },
    { key: "category", kind: "text", getValue: (row) => row.category },
    { key: "echelon", kind: "text", getValue: (row) => row.echelon },
    { key: "minimum", kind: "range", getValue: (row) => row.base_salary },
  ]);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });
  const columns: ColumnDef<Grade>[] = [
    { key: "code", header: t("hr.org.code"), defaultWidth: 110, cell: (row) => <span className="font-medium">{row.code}</span>, filterCell: text("code", t("hr.org.code")), sortValue: (row) => row.code },
    { key: "category", header: t("hr.org.grade.category"), defaultWidth: 200, cell: (row) => row.category, filterCell: text("category", t("hr.org.grade.category")), sortValue: (row) => row.category },
    { key: "echelon", header: t("hr.org.grade.echelon"), defaultWidth: 110, cell: (row) => row.echelon, filterCell: text("echelon", t("hr.org.grade.echelon")), sortValue: (row) => row.echelon },
    {
      key: "minimum",
      header: t("hr.org.grade.minimum"),
      defaultWidth: 180,
      cell: (row) => <span className="tabular-nums">{formatXof(row.base_salary)}</span>,
      filterCell: {
        type: "range",
        min: filters.range.minimum?.min ?? "",
        max: filters.range.minimum?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("minimum", "min", value),
        onMaxChange: (value) => filters.setRangeValue("minimum", "max", value),
      },
      sortValue: (row) => row.base_salary,
    },
    { key: "valid_from", header: t("hr.org.grade.validFrom"), defaultWidth: 140, cell: (row) => formatDate(row.valid_from), sortValue: (row) => row.valid_from },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_positions") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, grade: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.org.tab.grades")}</CardTitle>
        {hasPermission("hr.manage_positions") && (
          <Button onClick={() => setDialog({ open: true, grade: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.org.grade.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.organisation.grades"
          columns={columns}
          rows={filters.apply(grades)}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          loadingVariant="loader"
          empty={{ icon: <Layers className="h-5 w-5" />, title: t("hr.org.grade.empty.title"), description: t("hr.org.grade.empty.description") }}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <GradeDialog open={dialog.open} grade={dialog.grade} onOpenChange={(open) => setDialog((current) => ({ ...current, open }))} />
    </Card>
  );
}

function GradeDialog({ open, grade, onOpenChange }: { open: boolean; grade: Grade | null; onOpenChange: (open: boolean) => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", category: "", echelon: "", base_salary: "", valid_from: todayIso() });

  useEffect(() => {
    if (open)
      setForm({
        code: grade?.code ?? "",
        category: grade?.category ?? "",
        echelon: grade?.echelon ?? "",
        base_salary: grade ? String(grade.base_salary) : "",
        valid_from: grade?.valid_from ?? todayIso(),
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, grade?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: GradeInput = {
        code: form.code.trim(),
        category: form.category.trim(),
        echelon: form.echelon.trim(),
        base_salary: Number(form.base_salary),
        valid_from: form.valid_from,
      };
      return grade ? updateGrade(session!.token, grade.id, input) : createGrade(session!.token, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.grades });
      toast.success(t("hr.org.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.org.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(grade ? "hr.org.grade.editTitle" : "hr.org.grade.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.org.grade.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <div className="grid grid-cols-2 gap-3">
            <FormField id="grade-code" label={t("hr.org.code")}>
              <Input id="grade-code" required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} />
            </FormField>
            <FormField id="grade-from" label={t("hr.org.grade.validFrom")}>
              <Input id="grade-from" type="date" required value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} />
            </FormField>
            <FormField id="grade-category" label={t("hr.org.grade.category")}>
              <Input id="grade-category" required value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} />
            </FormField>
            <FormField id="grade-echelon" label={t("hr.org.grade.echelon")}>
              <Input id="grade-echelon" required value={form.echelon} onChange={(event) => setForm({ ...form, echelon: event.target.value })} />
            </FormField>
          </div>
          <FormField id="grade-minimum" label={t("hr.org.grade.minimum")}>
            <Input id="grade-minimum" type="number" min="0" step="1" required value={form.base_salary} onChange={(event) => setForm({ ...form, base_salary: event.target.value })} />
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
