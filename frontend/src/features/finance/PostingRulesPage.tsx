import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, GitBranch, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, textFilter } from "./LedgerTable";
import { errorText } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  RULE_KINDS,
  RULE_SOURCES,
  confirmPostingRule,
  createPostingRule,
  listAccounts,
  listJournals,
  listPostingRules,
  updatePostingRule,
  type PostingRule,
  type RuleSource,
  type RuleStatus,
} from "./ledgerApi";

export const SOURCE_KEYS: Record<RuleSource, TranslationKey> = {
  payroll: "finance.rules.source.payroll",
  invoice: "finance.rules.source.invoice",
  purchase_invoice: "finance.rules.source.purchase_invoice",
  treasury: "finance.rules.source.treasury",
};

export const KIND_KEYS: Record<string, TranslationKey> = {
  earning: "finance.rules.kind.earning",
  deduction: "finance.rules.kind.deduction",
  employee_contribution: "finance.rules.kind.employee_contribution",
  employer_contribution: "finance.rules.kind.employer_contribution",
  employer_charge: "finance.rules.kind.employer_charge",
  tax: "finance.rules.kind.tax",
  net: "finance.rules.kind.net",
  payment: "finance.rules.kind.payment",
  issued: "finance.rules.kind.issued",
  paid: "finance.rules.kind.paid",
  validated: "finance.rules.kind.validated",
  vat: "finance.rules.kind.vat",
  receipt_payment: "finance.rules.kind.receipt_payment",
  receipt_advance: "finance.rules.kind.receipt_advance",
  receipt_withheld: "finance.rules.kind.receipt_withheld",
  disbursement_payment: "finance.rules.kind.disbursement_payment",
  disbursement_advance: "finance.rules.kind.disbursement_advance",
  disbursement_withheld: "finance.rules.kind.disbursement_withheld",
  instrument_collected: "finance.rules.kind.instrument_collected",
  instrument_unpaid: "finance.rules.kind.instrument_unpaid",
  instrument_rejection_fee: "finance.rules.kind.instrument_rejection_fee",
  account_opening: "finance.rules.kind.account_opening",
};

export function kindLabel(t: (key: TranslationKey) => string, kind: string): string {
  const key = KIND_KEYS[kind];
  return key ? t(key) : kind;
}

export function PostingRulesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("finance.manage_posting_rules");
  const [sourceFilter, setSourceFilter] = useState<"all" | RuleSource>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | RuleStatus>("all");
  const [editing, setEditing] = useState<PostingRule | "new" | null>(null);
  const { data: rules = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.rules, queryFn: () => listPostingRules(token) });

  const confirmMutation = useMutation({
    mutationFn: (id: string) => confirmPostingRule(token, id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.rules });
      toast.success(t("finance.rules.confirmed"));
    },
    onError: (error) => toast.error(t("finance.rules.confirmError"), { description: errorText(error) }),
  });

  const fields: FilterField<PostingRule>[] = [
    { key: "source_kind", kind: "text", getValue: (rule) => kindLabel(t, rule.source_kind) },
    { key: "code", kind: "text", getValue: (rule) => rule.code },
    { key: "debit_account_code", kind: "text", getValue: (rule) => rule.debit_account_code ?? "" },
    { key: "credit_account_code", kind: "text", getValue: (rule) => rule.credit_account_code ?? "" },
    { key: "journal_code", kind: "text", getValue: (rule) => rule.journal_code ?? "" },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(
    rules.filter(
      (rule) =>
        (sourceFilter === "all" || rule.source === sourceFilter) && (statusFilter === "all" || rule.status === statusFilter),
    ),
  );
  const toConfirm = rules.filter((rule) => rule.status === "to_confirm").length;
  const accountCell = (code: string | null) => <span className="font-mono">{code ?? "—"}</span>;

  const columns: ColumnDef<PostingRule>[] = [
    {
      key: "source",
      header: t("finance.rules.column.source"),
      defaultWidth: 110,
      cell: (rule) => t(SOURCE_KEYS[rule.source]),
      sortValue: (rule) => rule.source,
    },
    {
      key: "source_kind",
      header: t("finance.rules.column.kind"),
      defaultWidth: 200,
      cell: (rule) => kindLabel(t, rule.source_kind),
      filterCell: textFilter(columnFilters, "source_kind", t("finance.rules.column.kind")),
      sortValue: (rule) => rule.source_kind,
    },
    {
      key: "code",
      header: t("finance.rules.column.code"),
      defaultWidth: 130,
      cell: (rule) => <span className="font-mono">{rule.code === "*" ? t("finance.rules.anyCode") : rule.code}</span>,
      filterCell: textFilter(columnFilters, "code", t("finance.rules.column.code")),
      sortValue: (rule) => rule.code,
    },
    {
      key: "debit_account_code",
      header: t("finance.rules.column.debit"),
      defaultWidth: 110,
      cell: (rule) => accountCell(rule.debit_account_code),
      filterCell: textFilter(columnFilters, "debit_account_code", t("finance.rules.column.debit")),
      sortValue: (rule) => rule.debit_account_code ?? "",
    },
    {
      key: "credit_account_code",
      header: t("finance.rules.column.credit"),
      defaultWidth: 110,
      cell: (rule) => accountCell(rule.credit_account_code),
      filterCell: textFilter(columnFilters, "credit_account_code", t("finance.rules.column.credit")),
      sortValue: (rule) => rule.credit_account_code ?? "",
    },
    {
      key: "journal_code",
      header: t("finance.rules.column.journal"),
      defaultWidth: 100,
      cell: (rule) => accountCell(rule.journal_code),
      filterCell: textFilter(columnFilters, "journal_code", t("finance.rules.column.journal")),
      sortValue: (rule) => rule.journal_code ?? "",
    },
    {
      key: "status",
      header: t("finance.rules.column.status"),
      defaultWidth: 130,
      cell: (rule) =>
        rule.status === "confirmed" ? (
          <Badge variant="success">{t("finance.rules.status.confirmed")}</Badge>
        ) : (
          <Badge variant="warning">{t("finance.rules.status.to_confirm")}</Badge>
        ),
      sortValue: (rule) => rule.status,
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (rule) =>
        canManage ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditing(rule)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            {rule.status === "to_confirm" && (
              <Button
                size="sm"
                variant="outline"
                disabled={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate(rule.id)}
              >
                <Check className="h-3.5 w-3.5" />
                {t("finance.rules.confirm")}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.rules.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.rules.subtitle")}</p>
        </div>
        {canManage && (
          <Button onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" />
            {t("finance.rules.new")}
          </Button>
        )}
      </div>
      {toConfirm > 0 && (
        <div className="rounded-md border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
          {toConfirm} {t("finance.rules.toConfirmBanner")}
        </div>
      )}
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.rules.tableTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.postingRules"
            columns={columns}
            rows={rows}
            rowKey={(rule) => rule.id}
            isLoading={isLoading}
            emptyIcon={<GitBranch className="h-5 w-5" />}
            emptyTitle={t("finance.rules.emptyTitle")}
            emptyDescription={t("finance.rules.emptyDescription")}
            toolbar={
              <>
                <FilterTabs
                  value={sourceFilter}
                  onChange={setSourceFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    ...RULE_SOURCES.map((source) => ({ value: source, label: t(SOURCE_KEYS[source]) })),
                  ]}
                />
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "to_confirm", label: t("finance.rules.status.to_confirm") },
                    { value: "confirmed", label: t("finance.rules.status.confirmed") },
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      {editing !== null && <RuleDialog rule={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function RuleDialog({ rule, onClose }: { rule: PostingRule | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });
  const { data: journals = [] } = useQuery({ queryKey: LEDGER_KEYS.journals, queryFn: () => listJournals(token) });
  const postable = accounts.filter((account) => account.is_postable);
  const schema = useMemo(
    () =>
      z
        .object({
          source: z.enum(RULE_SOURCES),
          source_kind: z.string().min(1, t("common.required")),
          code: z.string().trim().min(1, t("common.required")),
          debit_account_code: z.string(),
          credit_account_code: z.string(),
          journal_code: z.string(),
        })
        .refine((values) => values.debit_account_code !== "" || values.credit_account_code !== "", {
          message: t("finance.rules.needsAccount"),
          path: ["debit_account_code"],
        }),
    [t],
  );
  type RuleForm = z.infer<typeof schema>;
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    formState: { errors },
  } = useForm<RuleForm>({
    resolver: zodResolver(schema),
    defaultValues: rule
      ? {
          source: rule.source,
          source_kind: rule.source_kind,
          code: rule.code,
          debit_account_code: rule.debit_account_code ?? "",
          credit_account_code: rule.credit_account_code ?? "",
          journal_code: rule.journal_code ?? "",
        }
      : {
          source: "payroll",
          source_kind: "employee_contribution",
          code: "",
          debit_account_code: "",
          credit_account_code: "",
          journal_code: "",
        },
  });
  const source = watch("source");
  useEffect(() => {
    if (!RULE_KINDS[source].includes(getValues("source_kind"))) setValue("source_kind", RULE_KINDS[source][0]);
  }, [source, getValues, setValue]);

  const mutation = useMutation({
    mutationFn: (values: RuleForm) =>
      rule
        ? updatePostingRule(token, rule.id, {
            debit_account_code: values.debit_account_code,
            credit_account_code: values.credit_account_code,
            journal_code: values.journal_code,
          })
        : createPostingRule(token, {
            source: values.source,
            source_kind: values.source_kind,
            code: values.code,
            debit_account_code: values.debit_account_code || null,
            credit_account_code: values.credit_account_code || null,
            journal_code: values.journal_code || null,
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.rules });
      toast.success(t(rule ? "finance.rules.updated" : "finance.rules.created"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.rules.saveError"), { description: errorText(error) }),
  });

  const accountOptions = (
    <>
      <option value="">{t("common.none")}</option>
      {postable.map((account) => (
        <option key={account.code} value={account.code}>
          {account.code} · {account.name}
        </option>
      ))}
    </>
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(rule ? "finance.rules.editTitle" : "finance.rules.newTitle")}</DialogTitle>
          <DialogDescription>{t("finance.rules.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
          {rule ? (
            // Source, kind and code are the rule's key: shown, not edited (they stay in the form values).
            <p className="text-sm">
              <span className="font-medium">{t(SOURCE_KEYS[rule.source])}</span> · {kindLabel(t, rule.source_kind)} ·{" "}
              <span className="font-mono">{rule.code === "*" ? t("finance.rules.anyCode") : rule.code}</span>
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="rule_source">{t("finance.rules.column.source")}</Label>
                <Select id="rule_source" {...register("source")}>
                  {RULE_SOURCES.map((option) => (
                    <option key={option} value={option}>
                      {t(SOURCE_KEYS[option])}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rule_kind">{t("finance.rules.column.kind")}</Label>
                <Select id="rule_kind" {...register("source_kind")}>
                  {RULE_KINDS[source].map((kind) => (
                    <option key={kind} value={kind}>
                      {kindLabel(t, kind)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rule_code">{t("finance.rules.column.code")}</Label>
                <Input id="rule_code" placeholder="*" {...register("code")} />
                {source === "treasury" && <p className="text-xs text-muted-foreground">{t("finance.rules.treasuryCodeHint")}</p>}
                {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
              </div>
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rule_debit">{t("finance.rules.column.debit")}</Label>
              <Select id="rule_debit" {...register("debit_account_code")}>
                {accountOptions}
              </Select>
              {errors.debit_account_code && <p className="text-sm text-destructive">{errors.debit_account_code.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule_credit">{t("finance.rules.column.credit")}</Label>
              <Select id="rule_credit" {...register("credit_account_code")}>
                {accountOptions}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule_journal">{t("finance.rules.column.journal")}</Label>
              <Select id="rule_journal" {...register("journal_code")}>
                <option value="">{t("common.none")}</option>
                {journals.map((journal) => (
                  <option key={journal.code} value={journal.code}>
                    {journal.code} · {journal.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
