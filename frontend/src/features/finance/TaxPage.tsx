import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Percent, Plus, Receipt } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { LedgerTable } from "./LedgerTable";
import { errorText, formatAmount, monthEndIso, monthStartIso } from "./ledgerFormat";
import {
  TAX_KEYS,
  createTaxCode,
  getVatReport,
  invalidateTaxData,
  listTaxCodes,
  setDefaultTaxCode,
  updateTaxCode,
  type TaxCode,
  type TaxScope,
  type VatRateRow,
} from "./taxApi";

export function TaxPage() {
  const { t } = useI18n();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.tax.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.tax.subtitle")}</p>
      </div>
      <VatReportCard />
      <TaxCodesCard />
    </div>
  );
}

function VatReportCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const defaultRange = { from: monthStartIso(), to: monthEndIso() };
  const [range, setRange] = useState(defaultRange);
  const { data, isLoading } = useQuery({
    queryKey: TAX_KEYS.report(range.from, range.to),
    queryFn: () => getVatReport(token, range.from, range.to),
  });
  const rows = data?.sales_by_rate ?? [];
  const ledger = data?.ledger;
  const money = (value: number | null | undefined) => (value === null || value === undefined ? "—" : formatAmount(value));
  const columns: ColumnDef<VatRateRow>[] = [
    {
      key: "vat_rate",
      header: t("finance.tax.report.rate"),
      defaultWidth: 200,
      cell: (row) => (
        <span className="flex items-center gap-2">
          <span className="tabular-nums">{row.vat_rate} %</span>
          {row.exempt && <Badge>{t("finance.tax.report.exempt")}</Badge>}
        </span>
      ),
      sortValue: (row) => row.vat_rate,
    },
    {
      key: "base",
      header: t("finance.tax.report.base"),
      defaultWidth: 160,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatAmount(row.base),
      sortValue: (row) => row.base,
    },
    {
      key: "vat",
      header: t("finance.tax.report.vat"),
      defaultWidth: 160,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatAmount(row.vat),
      sortValue: (row) => row.vat,
    },
  ];
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <CardTitle>{t("finance.tax.report.title")}</CardTitle>
          <DateRangeFilter
            from={range.from}
            to={range.to}
            onChange={setRange}
            onReset={() => setRange(defaultRange)}
            isDefault={range.from === defaultRange.from && range.to === defaultRange.to}
          />
        </div>
        <p className="text-sm text-muted-foreground">{t("finance.tax.report.subtitle")}</p>
      </CardHeader>
      <CardContent className="space-y-4 p-0 pb-4">
        <div className="grid gap-3 px-6 sm:grid-cols-3">
          <Summary label={t("finance.tax.report.collected")} value={money(ledger?.collected)} account={ledger?.collected_account} />
          <Summary label={t("finance.tax.report.deductible")} value={money(ledger?.deductible)} account={ledger?.deductible_account} />
          <Summary label={t("finance.tax.report.payable")} value={money(ledger?.payable)} strong />
        </div>
        {data?.warnings.includes("NO_COLLECTED_VAT_ACCOUNT") && <p className="px-6 text-sm text-amber-600">{t("finance.tax.report.noCollected")}</p>}
        {data?.warnings.includes("NO_DEDUCTIBLE_VAT_ACCOUNT") && <p className="px-6 text-sm text-amber-600">{t("finance.tax.report.noDeductible")}</p>}
        <LedgerTable
          tableKey="finance.tax.salesByRate"
          columns={columns}
          rows={rows}
          rowKey={(row) => String(row.vat_rate)}
          isLoading={isLoading}
          loading="skeleton"
          emptyIcon={<Receipt className="h-5 w-5" />}
          emptyTitle={t("finance.tax.report.emptyTitle")}
          emptyDescription={t("finance.tax.report.emptyDescription")}
          footer={(key) => (key === "vat_rate" ? t("finance.entries.total") : key === "base" ? money(data?.sales_base) : key === "vat" ? money(data?.sales_vat) : "")}
        />
      </CardContent>
    </Card>
  );
}

function Summary({ label, value, account, strong }: { label: string; value: string; account?: string | null; strong?: boolean }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">
        {label}
        {account ? ` · ${account}` : ""}
      </div>
      <div className={`text-lg tabular-nums ${strong ? "font-semibold" : ""}`}>{value}</div>
    </div>
  );
}

function TaxCodesCard() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("finance.manage_tax_codes");
  const { data: codes = [], isLoading } = useQuery({ queryKey: TAX_KEYS.codes, queryFn: () => listTaxCodes(token) });
  const [form, setForm] = useState({ code: "", name: "", rate: "18", applies_to: "both" as TaxScope, exempt: false });

  const onError = (error: unknown) => toast.error(t("finance.tax.codes.error"), { description: errorText(error) });
  const createMutation = useMutation({
    mutationFn: () =>
      createTaxCode(token, {
        code: form.code,
        name_fr: form.name,
        name_en: form.name,
        rate: form.exempt ? 0 : Number(form.rate),
        applies_to: form.applies_to,
        exempt: form.exempt,
      }),
    onSuccess: () => {
      invalidateTaxData(queryClient);
      setForm({ code: "", name: "", rate: "18", applies_to: "both", exempt: false });
      toast.success(t("finance.tax.codes.created"));
    },
    onError,
  });
  const defaultMutation = useMutation({
    mutationFn: ({ id, side }: { id: string; side: "sales" | "purchase" }) => setDefaultTaxCode(token, id, side),
    onSuccess: () => {
      invalidateTaxData(queryClient);
      toast.success(t("finance.tax.codes.defaultSet"));
    },
    onError,
  });
  const activeMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => updateTaxCode(token, id, { active }),
    onSuccess: () => invalidateTaxData(queryClient),
    onError,
  });

  const scopeLabel = (scope: TaxScope) => t(`finance.tax.scope.${scope}`);
  const columns: ColumnDef<TaxCode>[] = [
    { key: "code", header: t("finance.tax.codes.code"), defaultWidth: 110, cell: (row) => <span className="font-mono">{row.code}</span>, sortValue: (row) => row.code },
    {
      key: "name",
      header: t("finance.tax.codes.name"),
      defaultWidth: 220,
      cell: (row) => (
        <span className="flex items-center gap-2">
          {language === "fr" ? row.name_fr : row.name_en}
          {row.exempt && <Badge>{t("finance.tax.report.exempt")}</Badge>}
          {!row.active && <Badge variant="warning">{t("finance.tax.codes.inactive")}</Badge>}
        </span>
      ),
      sortValue: (row) => row.name_en,
    },
    {
      key: "rate",
      header: t("finance.tax.report.rate"),
      defaultWidth: 90,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => `${row.rate} %`,
      sortValue: (row) => row.rate,
    },
    { key: "applies_to", header: t("finance.tax.codes.appliesTo"), defaultWidth: 120, cell: (row) => scopeLabel(row.applies_to), sortValue: (row) => row.applies_to },
    {
      key: "defaults",
      header: t("finance.tax.codes.defaultFor"),
      defaultWidth: 200,
      cell: (row) => (
        <span className="flex gap-1">
          {row.is_default_sales && <Badge variant="success">{t("finance.tax.scope.sales")}</Badge>}
          {row.is_default_purchase && <Badge variant="success">{t("finance.tax.scope.purchase")}</Badge>}
        </span>
      ),
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 320,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (row) =>
        canManage ? (
          <div className="flex flex-wrap justify-end gap-1">
            {row.active && row.applies_to !== "purchase" && !row.is_default_sales && (
              <Button size="sm" variant="outline" disabled={defaultMutation.isPending} onClick={() => defaultMutation.mutate({ id: row.id, side: "sales" })}>
                {t("finance.tax.codes.makeDefaultSales")}
              </Button>
            )}
            {row.active && row.applies_to !== "sales" && !row.is_default_purchase && (
              <Button size="sm" variant="outline" disabled={defaultMutation.isPending} onClick={() => defaultMutation.mutate({ id: row.id, side: "purchase" })}>
                {t("finance.tax.codes.makeDefaultPurchase")}
              </Button>
            )}
            {!row.is_default_sales && !row.is_default_purchase && (
              <Button size="sm" variant="ghost" disabled={activeMutation.isPending} onClick={() => activeMutation.mutate({ id: row.id, active: !row.active })}>
                {row.active ? t("finance.tax.codes.deactivate") : t("finance.tax.codes.activate")}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  const valid = form.code.trim() !== "" && form.name.trim() !== "" && (form.exempt || form.rate !== "");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("finance.tax.codes.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("finance.tax.codes.subtitle")}</p>
      </CardHeader>
      <CardContent className="space-y-4 p-0 pb-2">
        {canManage && (
          <form
            className="flex flex-wrap items-end gap-2 px-6"
            onSubmit={(event) => {
              event.preventDefault();
              if (valid) createMutation.mutate();
            }}
          >
            <Input className="h-9 w-28" placeholder={t("finance.tax.codes.code")} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} aria-label={t("finance.tax.codes.code")} />
            <Input className="h-9 w-52" placeholder={t("finance.tax.codes.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label={t("finance.tax.codes.name")} />
            <Input
              className="h-9 w-24"
              type="number"
              min={0}
              max={100}
              step="0.01"
              disabled={form.exempt}
              value={form.exempt ? "0" : form.rate}
              onChange={(e) => setForm({ ...form, rate: e.target.value })}
              aria-label={t("finance.tax.report.rate")}
            />
            <select
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={form.applies_to}
              onChange={(e) => setForm({ ...form, applies_to: e.target.value as TaxScope })}
              aria-label={t("finance.tax.codes.appliesTo")}
            >
              {(["both", "sales", "purchase"] as const).map((scope) => (
                <option key={scope} value={scope}>
                  {scopeLabel(scope)}
                </option>
              ))}
            </select>
            <label className="flex h-9 items-center gap-2 text-sm">
              <input type="checkbox" checked={form.exempt} onChange={(e) => setForm({ ...form, exempt: e.target.checked })} />
              {t("finance.tax.codes.exempt")}
            </label>
            <Button type="submit" disabled={!valid || createMutation.isPending}>
              <Plus className="h-4 w-4" />
              {t("common.create")}
            </Button>
          </form>
        )}
        <LedgerTable
          tableKey="finance.tax.codes"
          columns={columns}
          rows={codes}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          loading="skeleton"
          emptyIcon={<Percent className="h-5 w-5" />}
          emptyTitle={t("finance.tax.codes.emptyTitle")}
          emptyDescription={t("finance.tax.codes.emptyDescription")}
        />
      </CardContent>
    </Card>
  );
}
