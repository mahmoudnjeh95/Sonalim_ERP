import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRightCircle, Pencil, Target, ThumbsDown, Trophy } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Skeleton } from "../../../components/ui/skeleton";
import { StatCard } from "../../../components/patterns/StatCard";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StatusBadge, PriorityBadge } from "../../../components/patterns/StatusBadge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { listPartners } from "../../partners/api";
import { listOpportunities, NEXT_STAGES, transitionOpportunity, type Opportunity } from "./api";
import { OpportunityFormDialog } from "./OpportunityFormDialog";
import { MarkLostDialog } from "./MarkLostDialog";
import { MarkWonDialog } from "./MarkWonDialog";

const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const DASHBOARD_QUERY_KEY = ["crm", "dashboard"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;
type StageFilter = "all" | "open" | "won" | "lost";

function formatCurrency(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { style: "currency", currency: "XOF", maximumFractionDigits: 0 }).format(amount);
}

export function OpportunitiesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingOpportunity, setEditingOpportunity] = useState<Opportunity | null>(null);
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");
  const [mineOnly, setMineOnly] = useState(false);
  const [losingOpportunity, setLosingOpportunity] = useState<Opportunity | null>(null);
  const [winningOpportunity, setWinningOpportunity] = useState<Opportunity | null>(null);

  const {
    data: opportunities = [],
    isLoading,
    isError: isListError,
  } = useQuery({ queryKey: OPPORTUNITIES_QUERY_KEY, queryFn: () => listOpportunities(token) });

  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const { data: users = [] } = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token) });
  const activePartners = partners.filter((p) => p.status === "active" && p.kind !== "supplier");
  const ownerName = (ownerId: string | null) => {
    if (!ownerId) return t("crm.opportunities.unassigned");
    const user = users.find((u) => u.id === ownerId);
    return user ? userDisplayName(user) : ownerId;
  };

  function openCreateDialog() {
    setEditingOpportunity(null);
    setDialogOpen(true);
  }

  function openEditDialog(opportunity: Opportunity) {
    setEditingOpportunity(opportunity);
    setDialogOpen(true);
  }

  const transitionMutation = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: Opportunity["stage"] }) =>
      transitionOpportunity(token, id, stage, { correlationId: crypto.randomUUID() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEY });
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
  const mineFilteredOpportunities = mineOnly ? stageFilteredOpportunities.filter((o) => o.owner_id === session!.userId) : stageFilteredOpportunities;

  const columnFilterFields: FilterField<Opportunity>[] = [
    { key: "name", kind: "text", getValue: (o) => o.name },
    { key: "account", kind: "text", getValue: (o) => partnerName(o.partner_id) },
    { key: "amount", kind: "range", getValue: (o) => o.amount },
    { key: "owner", kind: "text", getValue: (o) => ownerName(o.owner_id) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredOpportunities = columnFilters.apply(mineFilteredOpportunities);

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
      sortValue: (opportunity) => opportunity.name,
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
      sortValue: (opportunity) => partnerName(opportunity.partner_id),
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
      sortValue: (opportunity) => opportunity.amount,
    },
    {
      key: "probability",
      header: t("crm.opportunities.column.probability"),
      defaultWidth: 120,
      cell: (opportunity) => <span className="tabular-nums text-muted-foreground">{opportunity.probability}%</span>,
      sortValue: (opportunity) => opportunity.probability,
    },
    {
      key: "priority",
      header: t("crm.opportunities.column.priority"),
      defaultWidth: 110,
      cell: (opportunity) => <PriorityBadge priority={opportunity.priority} />,
      sortValue: (opportunity) => opportunity.priority,
    },
    {
      key: "owner",
      header: t("crm.opportunities.column.owner"),
      defaultWidth: 160,
      cell: (opportunity) => <span className="text-muted-foreground">{ownerName(opportunity.owner_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.owner ?? "",
        onChange: (v) => columnFilters.setTextValue("owner", v),
        placeholder: t("crm.opportunities.column.owner"),
      },
      sortValue: (opportunity) => ownerName(opportunity.owner_id),
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
      sortValue: (opportunity) => opportunity.expected_close_date,
    },
    {
      key: "stage",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("crm.opportunities.column.stage")}
          <HelpTooltip text={t("crm.opportunities.help.stage")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (opportunity) => <StatusBadge status={opportunity.stage} />,
      sortValue: (opportunity) => opportunity.stage,
    },
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
                onClick={() =>
                  advanceStage === "won"
                    ? setWinningOpportunity(opportunity)
                    : transitionMutation.mutate({ id: opportunity.id, stage: advanceStage })
                }
                disabled={isUpdating}
              >
                {advanceStage === "won" ? <Trophy className="h-3.5 w-3.5" /> : <ArrowRightCircle className="h-3.5 w-3.5" />}
                {isUpdating ? t("crm.opportunities.updating") : t("crm.opportunities.advance")}
              </Button>
            )}
            {nextStages.includes("lost") && (
              <Button size="sm" variant="ghost" onClick={() => setLosingOpportunity(opportunity)} disabled={isUpdating}>
                <ThumbsDown className="h-3.5 w-3.5" />
                {t("crm.opportunities.markLost")}
              </Button>
            )}
          </>
        );
      },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("crm.opportunities", columns);
  const sortedOpportunities = sortRows(filteredOpportunities);

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
          icon={<Trophy className="h-5 w-5" />}
          accent="success"
          unit="F CFA"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
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
            <Button variant={mineOnly ? "default" : "outline"} size="sm" onClick={() => setMineOnly((v) => !v)}>
              {t("crm.opportunities.filter.mine")}
            </Button>
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Button
            onClick={openCreateDialog}
            disabled={activePartners.length === 0}
            title={activePartners.length === 0 ? t("crm.opportunities.noAccounts") : undefined}
          >
            <Target className="h-4 w-4" />
            {t("crm.opportunities.new")}
          </Button>
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
                {sortedOpportunities.map((opportunity, i) => (
                  <motion.tr
                    key={opportunity.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className={cn(
                      "border-b border-border last:border-0 hover:bg-muted/50",
                      opportunity.stage === "won" && "bg-success-soft/40 hover:bg-success-soft/60",
                    )}
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

      <OpportunityFormDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setEditingOpportunity(null);
        }}
        opportunity={editingOpportunity}
      />
      <MarkLostDialog opportunity={losingOpportunity} onOpenChange={(open) => !open && setLosingOpportunity(null)} />
      <MarkWonDialog opportunity={winningOpportunity} onOpenChange={(open) => !open && setWinningOpportunity(null)} />
    </div>
  );
}
