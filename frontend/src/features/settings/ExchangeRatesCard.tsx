import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Coins, Plus } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { createCurrency, getTodayRates, recordExchangeRate, type TodayRate } from "./exchangeRatesApi";

const BASE_CURRENCY = "XOF";

const newCurrencySchema = z.object({
  code: z.string().length(3, "3-letter code"),
  name: z.string().min(1, "Required"),
});
type NewCurrencyForm = z.infer<typeof newCurrencySchema>;

const RATES_QUERY_KEY = ["core", "exchange-rates", "today"] as const;

export function ExchangeRatesCard() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const { data: rates = [] } = useQuery({ queryKey: RATES_QUERY_KEY, queryFn: () => getTodayRates(token) });

  useEffect(() => {
    setDrafts((prev) => {
      const next = { ...prev };
      for (const rate of rates) {
        if (next[rate.currency_code] === undefined) {
          next[rate.currency_code] = rate.rate_to_base !== null ? String(rate.rate_to_base) : "";
        }
      }
      return next;
    });
  }, [rates]);

  const saveMutation = useMutation({
    mutationFn: (input: { currency_code: string; rate_to_base: number }) =>
      recordExchangeRate(token, {
        currency_code: input.currency_code,
        rate_to_base: input.rate_to_base,
        effective_date: new Date().toISOString().slice(0, 10),
        source: "manual",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RATES_QUERY_KEY });
      toast.success(t("settings.exchangeRates.saved"));
    },
    onError: (error) => {
      toast.error(t("settings.exchangeRates.saveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewCurrencyForm>({ resolver: zodResolver(newCurrencySchema) });

  const createMutation = useMutation({
    mutationFn: (input: NewCurrencyForm) => createCurrency(token, { code: input.code.toUpperCase(), name: input.name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RATES_QUERY_KEY });
      setDialogOpen(false);
      reset();
      toast.success(t("settings.exchangeRates.created"));
    },
    onError: (error) => {
      toast.error(t("settings.exchangeRates.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function formatUpdated(rate: TodayRate) {
    if (rate.currency_code === BASE_CURRENCY) return t("settings.exchangeRates.baseCurrency");
    if (!rate.effective_date) return t("settings.exchangeRates.notSet");
    const date = new Date(rate.effective_date).toLocaleDateString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium" });
    return rate.is_today ? `${t("settings.exchangeRates.today")} · ${date}` : `${t("settings.exchangeRates.carriedForward")} · ${date}`;
  }

  const columns: ColumnDef<TodayRate>[] = [
    {
      key: "currency",
      header: t("settings.exchangeRates.column.currency"),
      defaultWidth: 140,
      cell: (rate) => <span className="font-medium">{rate.currency_code}</span>,
      sortValue: (rate) => rate.currency_code,
    },
    {
      key: "rate",
      header: t("settings.exchangeRates.column.rate"),
      defaultWidth: 160,
      cell: (rate) => {
        const isBase = rate.currency_code === BASE_CURRENCY;
        const draft = drafts[rate.currency_code] ?? "";
        if (isBase) return <span className="tabular-nums text-muted-foreground">1.000</span>;
        return (
          <Input
            type="number"
            step="any"
            className="h-8 w-32"
            value={draft}
            onChange={(event) => setDrafts((prev) => ({ ...prev, [rate.currency_code]: event.target.value }))}
          />
        );
      },
      sortValue: (rate) => rate.rate_to_base,
    },
    {
      key: "updated",
      header: t("settings.exchangeRates.column.updated"),
      defaultWidth: 200,
      cell: (rate) => {
        const isBase = rate.currency_code === BASE_CURRENCY;
        if (isBase) return <span className="text-muted-foreground">{formatUpdated(rate)}</span>;
        return (
          <Badge variant={rate.is_today ? "success" : rate.effective_date ? "warning" : "default"} dot>
            {formatUpdated(rate)}
          </Badge>
        );
      },
      sortValue: (rate) => rate.effective_date,
    },
    {
      key: "action",
      header: "",
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (rate) => {
        const isBase = rate.currency_code === BASE_CURRENCY;
        const draft = drafts[rate.currency_code] ?? "";
        const parsed = Number(draft);
        const canSave = !isBase && draft.trim() !== "" && Number.isFinite(parsed) && parsed > 0;
        return (
          !isBase && (
            <Button
              size="sm"
              variant="outline"
              disabled={!canSave || saveMutation.isPending}
              onClick={() => saveMutation.mutate({ currency_code: rate.currency_code, rate_to_base: parsed })}
            >
              <Coins className="h-3.5 w-3.5" />
              {saveMutation.isPending && saveMutation.variables?.currency_code === rate.currency_code
                ? t("settings.exchangeRates.saving")
                : t("settings.exchangeRates.save")}
            </Button>
          )
        );
      },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("settings.exchangeRates", columns);
  const sortedRates = sortRows(rates);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("settings.exchangeRates.title")}</CardTitle>
          <CardDescription>{t("settings.exchangeRates.description")}</CardDescription>
        </div>
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button variant="ghost" size="sm">
              <Plus className="h-3.5 w-3.5" />
              {t("settings.exchangeRates.addCurrency")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("settings.exchangeRates.dialog.title")}</DialogTitle>
              <DialogDescription>{t("settings.exchangeRates.dialog.description")}</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
              <div className="space-y-1.5">
                <Label htmlFor="currency-code">{t("settings.exchangeRates.field.code")}</Label>
                <Input id="currency-code" placeholder="e.g. NGN" maxLength={3} {...register("code")} />
                {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="currency-name">{t("settings.exchangeRates.field.name")}</Label>
                <Input id="currency-name" placeholder="e.g. Nigerian Naira" {...register("name")} />
                {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
              </div>
              {createMutation.isError && (
                <p className="text-sm text-destructive">
                  {createMutation.error instanceof ApiError ? createMutation.error.message : t("settings.exchangeRates.createError")}
                </p>
              )}
              <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                {createMutation.isPending ? t("settings.exchangeRates.creating") : t("settings.exchangeRates.create")}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent className="p-0">
        <Table colWidths={colWidths}>
          <TableHeader>
            <TableRow>
              {visibleColumns.map((column) => (
                <ResizableTableHead
                  key={column.key}
                  width={getWidth(column.key)}
                  onResize={(width) => setWidth(column.key, width)}
                  className={column.headerClassName}
                  sortDirection={sortDirectionFor(column.key)}
                  onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedRates.map((rate) => (
              <TableRow key={rate.currency_code}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(rate)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
