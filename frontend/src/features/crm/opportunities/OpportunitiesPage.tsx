import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRightCircle, BadgeDollarSign, Pencil, Target, ThumbsDown, Trophy } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Skeleton } from "../../../components/ui/skeleton";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../../components/ui/dialog";
import { StatCard } from "../../../components/patterns/StatCard";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StatusBadge } from "../../../components/patterns/StatusBadge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { listPartners } from "../../partners/api";
import {
  createOpportunity,
  listOpportunities,
  NEXT_STAGES,
  transitionOpportunity,
  updateOpportunity,
  type Opportunity,
} from "./api";

const newOpportunitySchema = z.object({
  partner_id: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  amount: z.coerce.number().min(0, "Must be >= 0"),
  expected_close_date: z.string().optional(),
});
type NewOpportunityForm = z.infer<typeof newOpportunitySchema>;

const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
type StageFilter = "all" | "open" | "won" | "lost";

function formatCurrency(amount: number) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(amount);
}

export function OpportunitiesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingOpportunity, setEditingOpportunity] = useState<Opportunity | null>(null);
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");

  const {
    data: opportunities = [],
    isLoading,
    isError: isListError,
  } = useQuery({ queryKey: OPPORTUNITIES_QUERY_KEY, queryFn: () => listOpportunities(token) });

  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const activePartners = partners.filter((p) => p.status === "active" && p.kind !== "supplier");

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewOpportunityForm>({ resolver: zodResolver(newOpportunitySchema), defaultValues: { amount: 0 } });

  const createMutation = useMutation({
    mutationFn: (input: NewOpportunityForm) =>
      createOpportunity(token, { ...input, expected_close_date: input.expected_close_date || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      setDialogOpen(false);
      reset({ amount: 0 });
      toast.success(t("crm.opportunities.created"));
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewOpportunityForm) =>
      updateOpportunity(token, editingOpportunity!.id, {
        ...input,
        expected_close_date: input.expected_close_date || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      setDialogOpen(false);
      setEditingOpportunity(null);
      reset({ amount: 0 });
      toast.success(t("crm.opportunities.updated"));
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingOpportunity(null);
    reset({ partner_id: "", name: "", amount: 0, expected_close_date: "" });
    setDialogOpen(true);
  }

  function openEditDialog(opportunity: Opportunity) {
    setEditingOpportunity(opportunity);
    reset({
      partner_id: opportunity.partner_id,
      name: opportunity.name,
      amount: opportunity.amount,
      expected_close_date: opportunity.expected_close_date ?? "",
    });
    setDialogOpen(true);
  }

  const transitionMutation = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: Opportunity["stage"] }) => transitionOpportunity(token, id, stage),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      toast.success(t("crm.opportunities.updated"));
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const openCount = opportunities.filter((o) => o.stage !== "won" && o.stage !== "lost").length;
  const wonTotal = opportunities.filter((o) => o.stage === "won").reduce((sum, o) => sum + o.amount, 0);
  const partnerName = (partnerId: string) => partners.find((p) => p.id === partnerId)?.name ?? partnerId;
  const stageFilteredOpportunities =
    stageFilter === "all"
      ? opportunities
      : stageFilter === "open"
        ? opportunities.filter((o) => o.stage !== "won" && o.stage !== "lost")
        : opportunities.filter((o) => o.stage === stageFilter);

  const columnFilterFields: FilterField<Opportunity>[] = [
    { key: "name", kind: "text", getValue: (o) => o.name },
    { key: "account", kind: "text", getValue: (o) => partnerName(o.partner_id) },
    { key: "amount", kind: "range", getValue: (o) => o.amount },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredOpportunities = columnFilters.apply(stageFilteredOpportunities);

  const columns: ColumnDef<Opportunity>[] = [
    {
      key: "name",
      header: t("crm.opportunities.column.name"),
      defaultWidth: 200,
      cell: (opportunity) => <span className="font-medium">{opportunity.name}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("crm.opportunities.column.name"),
      },
    },
    {
      key: "account",
      header: t("crm.opportunities.column.account"),
      defaultWidth: 180,
      cell: (opportunity) => <span className="text-muted-foreground">{partnerName(opportunity.partner_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.account ?? "",
        onChange: (v) => columnFilters.setTextValue("account", v),
        placeholder: t("crm.opportunities.column.account"),
      },
    },
    {
      key: "amount",
      header: t("crm.opportunities.column.amount"),
      defaultWidth: 140,
      cell: (opportunity) => <span className="tabular-nums">{formatCurrency(opportunity.amount)}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.amount?.min ?? "",
        max: columnFilters.range.amount?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("amount", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("amount", "max", v),
      },
    },
    {
      key: "closeDate",
      header: t("crm.opportunities.column.closeDate"),
      defaultWidth: 140,
      cell: (opportunity) => (
        <span className="text-muted-foreground">
          {opportunity.expected_close_date ? new Date(opportunity.expected_close_date).toLocaleDateString() : "—"}
        </span>
      ),
    },
    { key: "stage", header: t("crm.opportunities.column.stage"), defaultWidth: 140, cell: (opportunity) => <StatusBadge status={opportunity.stage} /> },
    {
      key: "action",
      header: t("crm.opportunities.column.action"),
      defaultWidth: 240,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "space-x-2 text-right",
      cell: (opportunity) => {
        const nextStages = NEXT_STAGES[opportunity.stage];
        const advanceStage = nextStages.find((stage) => stage !== "lost");
        const isUpdating = transitionMutation.isPending && transitionMutation.variables?.id === opportunity.id;
        return (
          <>
            <Button size="sm" variant="outline" onClick={() => openEditDialog(opportunity)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("crm.opportunities.edit")}
            </Button>
            {advanceStage && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => transitionMutation.mutate({ id: opportunity.id, stage: advanceStage })}
                disabled={isUpdating}
              >
                {advanceStage === "won" ? <Trophy className="h-3.5 w-3.5" /> : <ArrowRightCircle className="h-3.5 w-3.5" />}
                {isUpdating ? t("crm.opportunities.updating") : t("crm.opportunities.advance")}
              </Button>
            )}
            {nextStages.includes("lost") && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => transitionMutation.mutate({ id: opportunity.id, stage: "lost" })}
                disabled={isUpdating}
              >
                <ThumbsDown className="h-3.5 w-3.5" />
                {t("crm.opportunities.markLost")}
              </Button>
            )}
          </>
        );
      },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "crm.opportunities",
    columns,
  );

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("crm.opportunities.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("crm.opportunities.subtitle")}</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("crm.opportunities.stat.total")} value={opportunities.length} icon={<Target className="h-5 w-5" />} />
        <StatCard label={t("crm.opportunities.stat.open")} value={openCount} icon={<ArrowRightCircle className="h-5 w-5" />} accent="warning" />
        <StatCard
          label={t("crm.opportunities.stat.won")}
          value={Math.round(wonTotal)}
          icon={<BadgeDollarSign className="h-5 w-5" />}
          accent="success"
          prefix="$"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <CardTitle>{t("crm.opportunities.table.title")}</CardTitle>
            <FilterTabs
              value={stageFilter}
              onChange={setStageFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "open", label: t("crm.opportunities.stat.open") },
                { value: "won", label: t("status.won") },
                { value: "lost", label: t("status.lost") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog
            open={dialogOpen}
            onOpenChange={(open) => {
              setDialogOpen(open);
              if (!open) setEditingOpportunity(null);
            }}
          >
            <DialogTrigger asChild>
              <Button
                onClick={openCreateDialog}
                disabled={activePartners.length === 0}
                title={activePartners.length === 0 ? t("crm.opportunities.noAccounts") : undefined}
              >
                <Target className="h-4 w-4" />
                {t("crm.opportunities.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {editingOpportunity ? t("crm.opportunities.dialog.editTitle") : t("crm.opportunities.dialog.title")}
                </DialogTitle>
                <DialogDescription>
                  {editingOpportunity
                    ? t("crm.opportunities.dialog.editDescription")
                    : t("crm.opportunities.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingOpportunity ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="partner_id">{t("crm.opportunities.field.account")}</Label>
                  <Select id="partner_id" {...register("partner_id")}>
                    <option value="">—</option>
                    {activePartners.map((partner) => (
                      <option key={partner.id} value={partner.id}>
                        {partner.name}
                      </option>
                    ))}
                  </Select>
                  {errors.partner_id && <p className="text-sm text-destructive">{errors.partner_id.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="name">{t("crm.opportunities.field.name")}</Label>
                  <Input id="name" {...register("name")} />
                  {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="amount">{t("crm.opportunities.field.amount")}</Label>
                    <Input id="amount" type="number" step="any" {...register("amount")} />
                    {errors.amount && <p className="text-sm text-destructive">{errors.amount.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="expected_close_date">{t("crm.opportunities.field.closeDate")}</Label>
                    <Input id="expected_close_date" type="date" {...register("expected_close_date")} />
                  </div>
                </div>
                {(editingOpportunity ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingOpportunity ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingOpportunity ? updateMutation.error : createMutation.error)?.message
                      : t(editingOpportunity ? "crm.opportunities.updateError" : "crm.opportunities.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingOpportunity ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingOpportunity
                    ? updateMutation.isPending
                      ? t("crm.opportunities.updating")
                      : t("crm.opportunities.update")
                    : createMutation.isPending
                      ? t("crm.opportunities.creating")
                      : t("crm.opportunities.create")}
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
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {isListError && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="py-8 text-center text-destructive">
                    {t("crm.opportunities.loadError")}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading && !isListError && filteredOpportunities.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Target className="h-5 w-5" />}
                      title={t("crm.opportunities.empty.title")}
                      description={t("crm.opportunities.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredOpportunities.map((opportunity, i) => (
                  <motion.tr
                    key={opportunity.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(opportunity)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
