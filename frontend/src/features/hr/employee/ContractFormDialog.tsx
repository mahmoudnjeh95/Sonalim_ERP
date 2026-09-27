import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  amendContract,
  CONTRACT_TYPES,
  createContract,
  hrKeys,
  listGrades,
  listPositions,
  PAY_FREQUENCIES,
  updateContract,
  type Contract,
  type ContractChanges,
  type ContractComponent,
  type ContractType,
  type PayFrequency,
} from "../api";
import { CONTRACT_TYPE_LABEL, PAY_FREQUENCY_LABEL } from "../employeeLabels";
import { emptyToNull, formatXof, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";

export type ContractDialogMode = "create" | "edit" | "amend";

interface ComponentRow {
  component_code: string;
  kind: "amount" | "rate";
  value: string;
}

interface ContractForm {
  contract_type: ContractType;
  start_date: string;
  end_date: string;
  trial_end_date: string;
  weekly_hours: string;
  base_salary: string;
  pay_frequency: PayFrequency;
  position_id: string;
  grade_id: string;
  draft: boolean;
  effective_date: string;
  components: ComponentRow[];
}

function toForm(contract: Contract | null): ContractForm {
  return {
    contract_type: contract?.contract_type ?? "cdi",
    start_date: contract?.start_date ?? todayIso(),
    end_date: contract?.end_date ?? "",
    trial_end_date: contract?.trial_end_date ?? "",
    // 40 h is the spec's default working week; HR changes it per contract.
    weekly_hours: contract ? String(contract.weekly_hours) : "40",
    base_salary: contract?.base_salary == null ? "" : String(contract.base_salary),
    pay_frequency: contract?.pay_frequency ?? "monthly",
    position_id: contract?.position_id ?? "",
    grade_id: contract?.grade_id ?? "",
    draft: contract?.status === "draft",
    effective_date: todayIso(),
    components: (contract?.components ?? []).map((component) => ({
      component_code: component.component_code,
      kind: component.rate !== null ? "rate" : "amount",
      value: String(component.rate ?? component.amount ?? ""),
    })),
  };
}

function toComponents(rows: ComponentRow[]): ContractComponent[] {
  return rows
    .filter((row) => row.component_code.trim() !== "")
    .map((row) => ({
      component_code: row.component_code.trim().toUpperCase(),
      amount: row.kind === "amount" ? Number(row.value) : null,
      rate: row.kind === "rate" ? Number(row.value) : null,
    }));
}

/** What the user changed; an amendment never carries the start or trial dates. */
function changes(initial: ContractForm, form: ContractForm, mode: "edit" | "amend"): ContractChanges {
  const out: ContractChanges = {};
  if (form.contract_type !== initial.contract_type) out.contract_type = form.contract_type;
  if (mode === "edit" && form.start_date !== initial.start_date) out.start_date = form.start_date;
  if (form.end_date !== initial.end_date) out.end_date = emptyToNull(form.end_date);
  if (mode === "edit" && form.trial_end_date !== initial.trial_end_date) out.trial_end_date = emptyToNull(form.trial_end_date);
  if (form.weekly_hours !== initial.weekly_hours) out.weekly_hours = Number(form.weekly_hours);
  if (form.base_salary !== initial.base_salary) out.base_salary = Number(form.base_salary);
  if (form.pay_frequency !== initial.pay_frequency) out.pay_frequency = form.pay_frequency;
  if (form.position_id !== initial.position_id) out.position_id = emptyToNull(form.position_id);
  if (form.grade_id !== initial.grade_id) out.grade_id = emptyToNull(form.grade_id);
  if (JSON.stringify(form.components) !== JSON.stringify(initial.components)) out.components = toComponents(form.components);
  return out;
}

export function ContractFormDialog({
  open,
  onOpenChange,
  employeeId,
  mode,
  contract,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employeeId: string;
  mode: ContractDialogMode;
  contract: Contract | null;
}) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canSeeSensitive = hasPermission("hr.view_sensitive");
  const [initial, setInitial] = useState<ContractForm>(toForm(null));
  const [form, setForm] = useState<ContractForm>(toForm(null));

  useEffect(() => {
    if (!open) return;
    const start = toForm(mode === "create" ? null : contract);
    setInitial(start);
    setForm(start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, contract?.id]);

  const positions = useQuery({ queryKey: hrKeys.positions, queryFn: () => listPositions(token), enabled: open && hasPermission("hr.view_positions") });
  const grades = useQuery({ queryKey: hrKeys.grades, queryFn: () => listGrades(token), enabled: open && hasPermission("hr.view_positions") });
  const grade = (grades.data ?? []).find((entry) => entry.id === form.grade_id);

  const mutation = useMutation({
    mutationFn: () => {
      if (mode === "create") {
        return createContract(token, {
          employee_id: employeeId,
          contract_type: form.contract_type,
          start_date: form.start_date,
          base_salary: Number(form.base_salary),
          end_date: emptyToNull(form.end_date),
          trial_end_date: emptyToNull(form.trial_end_date),
          weekly_hours: Number(form.weekly_hours),
          pay_frequency: form.pay_frequency,
          position_id: emptyToNull(form.position_id),
          grade_id: emptyToNull(form.grade_id),
          status: form.draft ? "draft" : "active",
          components: toComponents(form.components),
        });
      }
      if (mode === "edit") return updateContract(token, contract!.id, changes(initial, form, "edit"));
      return amendContract(token, contract!.id, { effective_date: form.effective_date, ...changes(initial, form, "amend") });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t(mode === "amend" ? "hr.contracts.amended" : "hr.contracts.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.contracts.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const set = (patch: Partial<ContractForm>) => setForm((current) => ({ ...current, ...patch }));
  const setRow = (index: number, patch: Partial<ComponentRow>) =>
    set({ components: form.components.map((row, i) => (i === index ? { ...row, ...patch } : row)) });
  const payLocked = !canSeeSensitive;
  const title = mode === "create" ? "hr.contracts.dialog.createTitle" : mode === "edit" ? "hr.contracts.dialog.editTitle" : "hr.contracts.dialog.amendTitle";
  const description =
    mode === "create" ? "hr.contracts.dialog.createDescription" : mode === "edit" ? "hr.contracts.dialog.editDescription" : "hr.contracts.dialog.amendDescription";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t(title)}</DialogTitle>
          <DialogDescription>{t(description)}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {mode === "amend" && (
              <FormField id="contract-effective" label={t("hr.contracts.field.effectiveDate")}>
                <Input id="contract-effective" type="date" required value={form.effective_date} onChange={(event) => set({ effective_date: event.target.value })} />
              </FormField>
            )}
            <FormField id="contract-type" label={t("hr.contracts.field.type")}>
              <Select id="contract-type" value={form.contract_type} onChange={(event) => set({ contract_type: event.target.value as ContractType })}>
                {CONTRACT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {t(CONTRACT_TYPE_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            {mode !== "amend" && (
              <FormField id="contract-start" label={t("hr.contracts.field.start")}>
                <Input id="contract-start" type="date" required value={form.start_date} onChange={(event) => set({ start_date: event.target.value })} />
              </FormField>
            )}
            <FormField id="contract-end" label={t("hr.contracts.field.end")}>
              <Input id="contract-end" type="date" value={form.end_date} onChange={(event) => set({ end_date: event.target.value })} />
            </FormField>
            {mode !== "amend" && (
              <FormField id="contract-trial" label={t("hr.contracts.field.trialEnd")}>
                <Input id="contract-trial" type="date" value={form.trial_end_date} onChange={(event) => set({ trial_end_date: event.target.value })} />
              </FormField>
            )}
            <FormField id="contract-hours" label={t("hr.contracts.field.hours")}>
              <Input id="contract-hours" type="number" min="1" max="168" step="0.5" required value={form.weekly_hours} onChange={(event) => set({ weekly_hours: event.target.value })} />
            </FormField>
            <FormField id="contract-frequency" label={t("hr.contracts.field.frequency")}>
              <Select id="contract-frequency" value={form.pay_frequency} onChange={(event) => set({ pay_frequency: event.target.value as PayFrequency })}>
                {PAY_FREQUENCIES.map((value) => (
                  <option key={value} value={value}>
                    {t(PAY_FREQUENCY_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField
              id="contract-pay"
              label={t("hr.contracts.field.pay")}
              hint={payLocked ? t("hr.sensitive.readOnly") : grade ? `${t("hr.contracts.gradeMinimum")}: ${formatXof(grade.base_salary)}` : undefined}
            >
              <Input
                id="contract-pay"
                type="number"
                min="0"
                step="1"
                required={mode === "create"}
                readOnly={payLocked}
                className={payLocked ? "bg-muted" : undefined}
                placeholder={payLocked ? "••••" : undefined}
                value={form.base_salary}
                onChange={(event) => set({ base_salary: event.target.value })}
              />
            </FormField>
            <FormField id="contract-position" label={t("hr.field.position")}>
              <Select id="contract-position" value={form.position_id} onChange={(event) => set({ position_id: event.target.value })}>
                <option value="">{t("hr.form.noneOption")}</option>
                {(positions.data ?? []).map((position) => (
                  <option key={position.id} value={position.id}>
                    {position.code} — {position.title}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField id="contract-grade" label={t("hr.field.grade")}>
              <Select id="contract-grade" value={form.grade_id} onChange={(event) => set({ grade_id: event.target.value })}>
                <option value="">{t("hr.form.noneOption")}</option>
                {(grades.data ?? []).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.code} — {entry.category} {entry.echelon}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">{t("hr.contracts.field.components")}</p>
            {form.components.map((row, index) => (
              <div key={index} className="grid grid-cols-[1fr_8rem_1fr_auto] items-end gap-2">
                <Input
                  aria-label={t("hr.contracts.field.componentCode")}
                  placeholder="TRANSPORT"
                  readOnly={payLocked}
                  value={row.component_code}
                  onChange={(event) => setRow(index, { component_code: event.target.value.toUpperCase() })}
                />
                <Select disabled={payLocked} value={row.kind} onChange={(event) => setRow(index, { kind: event.target.value as ComponentRow["kind"] })}>
                  <option value="amount">{t("hr.contracts.kind.amount")}</option>
                  <option value="rate">{t("hr.contracts.kind.rate")}</option>
                </Select>
                <Input
                  aria-label={t(row.kind === "amount" ? "hr.contracts.field.componentAmount" : "hr.contracts.field.componentRate")}
                  placeholder={payLocked ? "••••" : t(row.kind === "amount" ? "hr.contracts.field.componentAmount" : "hr.contracts.field.componentRate")}
                  type="number"
                  min="0"
                  step={row.kind === "amount" ? "1" : "0.01"}
                  readOnly={payLocked}
                  value={row.value}
                  onChange={(event) => setRow(index, { value: event.target.value })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={payLocked}
                  aria-label={t("hr.contracts.removeComponent")}
                  onClick={() => set({ components: form.components.filter((_, i) => i !== index) })}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={payLocked}
              onClick={() => set({ components: [...form.components, { component_code: "", kind: "amount", value: "" }] })}
            >
              <Plus className="h-3.5 w-3.5" />
              {t("hr.contracts.addComponent")}
            </Button>
          </div>

          {mode === "create" && (
            <div className="flex items-center gap-2">
              <Checkbox id="contract-draft" checked={form.draft} onCheckedChange={(checked) => set({ draft: checked === true })} />
              <Label htmlFor="contract-draft">{t("hr.contracts.field.statusDraft")}</Label>
            </div>
          )}

          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending
              ? t("common.saving")
              : t(mode === "create" ? "hr.contracts.create" : mode === "amend" ? "hr.contracts.saveAmendment" : "common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
