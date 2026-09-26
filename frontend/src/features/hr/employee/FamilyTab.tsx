import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  createDependant,
  DEPENDANT_KINDS,
  hrKeys,
  listDependants,
  updateDependant,
  type Dependant,
  type DependantInput,
  type DependantKind,
  type EmployeeRecord,
} from "../api";
import { DEPENDANT_KIND_LABEL } from "../employeeLabels";
import { emptyToNull, formatDate, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

type KindFilter = "all" | DependantKind;

export function FamilyTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [kind, setKind] = useState<KindFilter>("all");
  const [dialog, setDialog] = useState<{ open: boolean; dependant: Dependant | null }>({ open: false, dependant: null });
  const { data: dependants = [], isLoading } = useQuery({
    queryKey: hrKeys.dependants(employee.id),
    queryFn: () => listDependants(session!.token, employee.id),
  });
  const filters = useColumnFilters<Dependant>([{ key: "name", kind: "text", getValue: (row) => row.name }]);
  const rows = filters.apply(kind === "all" ? dependants : dependants.filter((row) => row.kind === kind));
  const kindOptions: { value: KindFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...DEPENDANT_KINDS.map((value) => ({ value, label: t(DEPENDANT_KIND_LABEL[value]) })),
  ];
  const canEdit = hasPermission("hr.admin_employees");

  const columns: ColumnDef<Dependant>[] = [
    {
      key: "name",
      header: t("hr.family.name"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{row.name}</span>,
      filterCell: { type: "text", value: filters.text.name ?? "", onChange: (value) => filters.setTextValue("name", value), placeholder: t("hr.family.name") },
      sortValue: (row) => row.name,
    },
    { key: "kind", header: t("hr.family.kind"), defaultWidth: 120, cell: (row) => t(DEPENDANT_KIND_LABEL[row.kind]), sortValue: (row) => row.kind },
    { key: "birth_date", header: t("hr.field.birthDate"), defaultWidth: 130, cell: (row) => formatDate(row.birth_date), sortValue: (row) => row.birth_date },
    { key: "tax", header: t("hr.family.forTax"), defaultWidth: 130, cell: (row) => t(row.dependent_for_tax ? "common.yes" : "common.no") },
    { key: "valid_from", header: t("hr.family.validFrom"), defaultWidth: 120, cell: (row) => formatDate(row.valid_from), sortValue: (row) => row.valid_from },
    { key: "valid_to", header: t("hr.family.validTo"), defaultWidth: 120, cell: (row) => formatDate(row.valid_to), sortValue: (row) => row.valid_to },
    {
      key: "today",
      header: t("hr.family.countsToday"),
      defaultWidth: 140,
      cell: (row) => <Badge variant={row.counts_for_tax_today ? "success" : "default"}>{t(row.counts_for_tax_today ? "common.yes" : "common.no")}</Badge>,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        canEdit ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, dependant: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle className="text-base">{t("hr.family.title")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {t("hr.family.taxCount")}: {dependants.filter((row) => row.counts_for_tax_today).length} · {t("hr.family.forTaxHint")}
          </p>
        </div>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialog({ open: true, dependant: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.family.add")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.employee.dependants"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <Users className="h-5 w-5" />, title: t("hr.family.empty.title"), description: t("hr.family.empty.description") }}
          toolbar={<FilterTabs value={kind} onChange={setKind} options={kindOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <DependantDialog
        employeeId={employee.id}
        open={dialog.open}
        dependant={dialog.dependant}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
      />
    </Card>
  );
}

interface DependantForm {
  kind: DependantKind;
  name: string;
  birth_date: string;
  dependent_for_tax: boolean;
  valid_from: string;
  valid_to: string;
}

function toForm(dependant: Dependant | null): DependantForm {
  return {
    kind: dependant?.kind ?? "child",
    name: dependant?.name ?? "",
    birth_date: dependant?.birth_date ?? "",
    dependent_for_tax: dependant?.dependent_for_tax ?? false,
    valid_from: dependant?.valid_from ?? todayIso(),
    valid_to: dependant?.valid_to ?? "",
  };
}

function DependantDialog({
  employeeId,
  open,
  dependant,
  onOpenChange,
}: {
  employeeId: string;
  open: boolean;
  dependant: Dependant | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<DependantForm>(toForm(null));

  useEffect(() => {
    if (open) setForm(toForm(dependant));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dependant?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: DependantInput = {
        kind: form.kind,
        name: form.name.trim(),
        birth_date: emptyToNull(form.birth_date),
        dependent_for_tax: form.dependent_for_tax,
        valid_from: form.valid_from,
        valid_to: emptyToNull(form.valid_to),
      };
      return dependant ? updateDependant(session!.token, dependant.id, input) : createDependant(session!.token, employeeId, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.dependants(employeeId) });
      toast.success(t("hr.family.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.family.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(dependant ? "hr.family.dialog.editTitle" : "hr.family.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.family.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <FormField id="dependant-kind" label={t("hr.family.kind")}>
              <Select id="dependant-kind" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as DependantKind })}>
                {DEPENDANT_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {t(DEPENDANT_KIND_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField id="dependant-name" label={t("hr.family.name")}>
              <Input id="dependant-name" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </FormField>
            <FormField id="dependant-birth" label={t("hr.field.birthDate")}>
              <Input id="dependant-birth" type="date" value={form.birth_date} onChange={(event) => setForm({ ...form, birth_date: event.target.value })} />
            </FormField>
            <FormField id="dependant-from" label={t("hr.family.validFrom")}>
              <Input id="dependant-from" type="date" required value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} />
            </FormField>
            <FormField id="dependant-to" label={t("hr.family.validTo")}>
              <Input id="dependant-to" type="date" value={form.valid_to} onChange={(event) => setForm({ ...form, valid_to: event.target.value })} />
            </FormField>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="dependant-tax"
              checked={form.dependent_for_tax}
              onCheckedChange={(checked) => setForm({ ...form, dependent_for_tax: checked === true })}
            />
            <Label htmlFor="dependant-tax">{t("hr.family.forTax")}</Label>
          </div>
          <p className="text-xs text-muted-foreground">{t("hr.family.forTaxHint")}</p>
          <Button type="submit" className="w-full" disabled={mutation.isPending || !form.name.trim() || !form.valid_from}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
