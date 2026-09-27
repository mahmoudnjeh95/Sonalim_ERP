import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, Wallet } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  hrKeys,
  listPaymentSets,
  MOBILE_OPERATORS,
  PAYMENT_METHODS,
  replacePaymentSet,
  type EmployeeRecord,
  type MobileOperator,
  type PaymentMethod,
  type PaymentMethodInput,
  type PaymentMethodKind,
  type PaymentSet,
} from "../api";
import { OPERATOR_LABEL, PAYMENT_METHOD_LABEL } from "../employeeLabels";
import { emptyToNull, formatDate, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";
import { Masked } from "../Masked";

export function PaymentTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const canSeeSensitive = hasPermission("hr.view_sensitive");
  const [dialog, setDialog] = useState<{ open: boolean; set: PaymentSet | null }>({ open: false, set: null });
  const { data: sets = [], isLoading } = useQuery({
    queryKey: hrKeys.paymentSets(employee.id),
    queryFn: () => listPaymentSets(session!.token, employee.id),
  });

  const describe = (method: PaymentMethod) => {
    if (method.method === "cash") return t("hr.payment.cashHint");
    const number = method.sensitive_hidden ? <Masked /> : method.method === "bank" ? method.account_no : method.mobile_number;
    const label = method.method === "bank" ? method.bank_name : method.mobile_operator ? t(OPERATOR_LABEL[method.mobile_operator]) : null;
    return (
      <span className="inline-flex items-center gap-1.5">
        {label} · {number}
      </span>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-muted-foreground">{t("hr.payment.help")}</p>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialog({ open: true, set: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.payment.new")}
          </Button>
        )}
      </div>
      {isLoading && <Skeleton className="h-32 w-full" />}
      {!isLoading && sets.length === 0 && (
        <Card>
          <CardContent className="p-0">
            <EmptyState icon={<Wallet className="h-5 w-5" />} title={t("hr.payment.empty.title")} description={t("hr.payment.empty.description")} />
          </CardContent>
        </Card>
      )}
      {sets.map((set) => (
        <Card key={set.valid_from}>
          <CardHeader className="flex-row items-center justify-between gap-3 pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              {t("hr.payment.from")} {formatDate(set.valid_from)}
              {set.in_force && <Badge variant="success">{t("hr.payment.inForce")}</Badge>}
            </CardTitle>
            {hasPermission("hr.admin_employees") && (canSeeSensitive || set.methods.every((method) => method.method === "cash")) && (
              <Button size="sm" variant="outline" onClick={() => setDialog({ open: true, set })}>
                <Pencil className="h-3.5 w-3.5" />
                {t("common.edit")}
              </Button>
            )}
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border text-sm">
              {set.methods.map((method) => (
                <li key={method.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="flex items-center gap-2 font-medium">
                    {t(PAYMENT_METHOD_LABEL[method.method])}
                    {method.is_primary && <Badge variant="primary">{t("hr.payment.primary")}</Badge>}
                  </span>
                  <span className="text-muted-foreground">{describe(method)}</span>
                  <span className="tabular-nums">{method.share_percent.toLocaleString(currentLocale())} %</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
      <PaymentSetDialog
        employeeId={employee.id}
        open={dialog.open}
        set={dialog.set}
        canSeeSensitive={canSeeSensitive}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
      />
    </div>
  );
}

interface MethodRow {
  method: PaymentMethodKind;
  bank_name: string;
  account_no: string;
  mobile_operator: MobileOperator;
  mobile_number: string;
  share_percent: string;
  is_primary: boolean;
}

function blankRow(primary: boolean, canSeeSensitive: boolean): MethodRow {
  return {
    method: canSeeSensitive ? "bank" : "cash",
    bank_name: "",
    account_no: "",
    mobile_operator: "orange_money",
    mobile_number: "",
    share_percent: primary ? "100" : "",
    is_primary: primary,
  };
}

function fromMethod(method: PaymentMethod): MethodRow {
  return {
    method: method.method,
    bank_name: method.bank_name ?? "",
    account_no: method.account_no ?? "",
    mobile_operator: method.mobile_operator ?? "orange_money",
    mobile_number: method.mobile_number ?? "",
    share_percent: String(method.share_percent),
    is_primary: method.is_primary,
  };
}

function toInput(row: MethodRow): PaymentMethodInput {
  const bank = row.method === "bank";
  const mobile = row.method === "mobile_money";
  return {
    method: row.method,
    share_percent: Number(row.share_percent),
    is_primary: row.is_primary,
    bank_name: bank ? emptyToNull(row.bank_name) : null,
    account_no: bank ? emptyToNull(row.account_no) : null,
    mobile_operator: mobile ? row.mobile_operator : null,
    mobile_number: mobile ? emptyToNull(row.mobile_number) : null,
  };
}

function PaymentSetDialog({
  employeeId,
  open,
  set,
  canSeeSensitive,
  onOpenChange,
}: {
  employeeId: string;
  open: boolean;
  set: PaymentSet | null;
  canSeeSensitive: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [validFrom, setValidFrom] = useState(todayIso());
  const [rows, setRows] = useState<MethodRow[]>([blankRow(true, canSeeSensitive)]);

  useEffect(() => {
    if (!open) return;
    setValidFrom(set?.valid_from ?? todayIso());
    setRows(set ? set.methods.map(fromMethod) : [blankRow(true, canSeeSensitive)]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, set?.valid_from]);

  const total = rows.reduce((sum, row) => sum + (Number(row.share_percent) || 0), 0);
  const mutation = useMutation({
    mutationFn: (methods: PaymentMethodInput[]) => replacePaymentSet(session!.token, employeeId, { valid_from: validFrom, methods }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.paymentSets(employeeId) });
      toast.success(t("hr.payment.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.payment.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });
  const update = (index: number, patch: Partial<MethodRow>) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : patch.is_primary ? { ...row, is_primary: false } : row)));
  const methodChoices: readonly PaymentMethodKind[] = canSeeSensitive ? PAYMENT_METHODS : ["cash"];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t(set ? "hr.payment.dialog.editTitle" : "hr.payment.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.payment.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate(rows.map(toInput));
          }}
        >
          <FormField id="payment-from" label={t("hr.payment.field.validFrom")}>
            <Input id="payment-from" type="date" required readOnly={set !== null} value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
          </FormField>
          {!canSeeSensitive && <p className="text-xs text-muted-foreground">{t("hr.payment.cashOnly")}</p>}
          {rows.map((row, index) => (
            <div key={index} className="grid grid-cols-1 items-end gap-2 rounded-lg border border-border p-3 sm:grid-cols-6">
              <FormField id={`method-${index}`} label={t("hr.payment.field.method")}>
                <Select id={`method-${index}`} value={row.method} onChange={(event) => update(index, { method: event.target.value as PaymentMethodKind })}>
                  {methodChoices.map((value) => (
                    <option key={value} value={value}>
                      {t(PAYMENT_METHOD_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              {row.method === "bank" && (
                <>
                  <FormField id={`bank-${index}`} label={t("hr.payment.field.bankName")}>
                    <Input id={`bank-${index}`} required value={row.bank_name} onChange={(event) => update(index, { bank_name: event.target.value })} />
                  </FormField>
                  <div className="sm:col-span-2">
                    <FormField id={`account-${index}`} label={t("hr.payment.field.accountNo")}>
                      <Input id={`account-${index}`} required value={row.account_no} onChange={(event) => update(index, { account_no: event.target.value })} />
                    </FormField>
                  </div>
                </>
              )}
              {row.method === "mobile_money" && (
                <>
                  <FormField id={`operator-${index}`} label={t("hr.payment.field.operator")}>
                    <Select id={`operator-${index}`} value={row.mobile_operator} onChange={(event) => update(index, { mobile_operator: event.target.value as MobileOperator })}>
                      {MOBILE_OPERATORS.map((value) => (
                        <option key={value} value={value}>
                          {t(OPERATOR_LABEL[value])}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                  <div className="sm:col-span-2">
                    <FormField id={`mobile-${index}`} label={t("hr.payment.field.mobileNumber")}>
                      <Input id={`mobile-${index}`} required value={row.mobile_number} onChange={(event) => update(index, { mobile_number: event.target.value })} />
                    </FormField>
                  </div>
                </>
              )}
              {row.method === "cash" && <div className="sm:col-span-3" />}
              <FormField id={`share-${index}`} label={t("hr.payment.field.share")}>
                <Input
                  id={`share-${index}`}
                  type="number"
                  min="0.01"
                  max="100"
                  step="0.01"
                  required
                  value={row.share_percent}
                  onChange={(event) => update(index, { share_percent: event.target.value })}
                />
              </FormField>
              <div className="flex items-center justify-between gap-2 sm:col-span-6">
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" name="primary-method" checked={row.is_primary} onChange={() => update(index, { is_primary: true })} />
                  {t("hr.payment.field.primary")}
                </label>
                {rows.length > 1 && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setRows(rows.filter((_, i) => i !== index))}>
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("hr.payment.removeMethod")}
                  </Button>
                )}
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setRows([...rows, blankRow(false, canSeeSensitive)])}>
              <Plus className="h-3.5 w-3.5" />
              {t("hr.payment.addMethod")}
            </Button>
            <span className={Math.abs(total - 100) < 0.005 ? "text-sm text-muted-foreground" : "text-sm font-medium text-destructive"}>
              {t("hr.payment.total")}: {total.toLocaleString(currentLocale())} / 100 %
            </span>
          </div>
          <div className="flex gap-2">
            {set && (
              <Button type="button" variant="outline" className="flex-1" disabled={mutation.isPending} onClick={() => mutation.mutate([])}>
                {t("hr.payment.removeSet")}
              </Button>
            )}
            <Button type="submit" className="flex-1" disabled={mutation.isPending}>
              {mutation.isPending ? t("common.saving") : t("common.save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
