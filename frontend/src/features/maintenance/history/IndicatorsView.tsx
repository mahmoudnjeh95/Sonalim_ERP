import { useMemo } from "react";
import { Gauge } from "lucide-react";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import ImmobilisationSvg from "../../../assets/icons/maintenance/immobilisation.svg?react";
import SparePartsSvg from "../../../assets/icons/maintenance/spare_parts.svg?react";
import WrenchSvg from "../../../assets/icons/maintenance/wrench.svg?react";
import HistoryEmptyIllustration from "../../../assets/illustrations/maintenance/history-empty.svg?react";
import { ColumnFilterRow, type FilterCell } from "../../../components/patterns/ColumnFilterRow";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { MobileCardList } from "../../../components/patterns/MobileCardList";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { StatCard } from "../../../components/patterns/StatCard";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";
import { CURRENCY_CODE, formatXofWithCode } from "../../../lib/currency";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useIsMobile } from "../../../lib/useIsMobile";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { cn } from "../../../lib/utils";
import type { IndicatorsResponse, MachineIndicators } from "./api";
import { fill, minutesOrDash } from "./historyFormat";
import { MachineThumb } from "./MachinePhoto";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const WrenchIcon = outlineIcon(WrenchSvg);
const ImmobilisationIcon = outlineIcon(ImmobilisationSvg);
const SparePartsIcon = outlineIcon(SparePartsSvg);

type Group = "machine" | "production" | "maintenance";
const GROUP_OF: Record<string, Group> = {
  machine: "machine",
  prod_breakdowns: "production",
  prod_stop: "production",
  mtbf: "production",
  mttr: "production",
  maint_breakdowns: "maintenance",
  immobilisation: "maintenance",
  preventive: "maintenance",
  technician: "maintenance",
  cost: "maintenance",
};

/** The "Selon la production | Selon la maintenance" row above the headers, spanning whichever columns are visible. */
function GroupRow({ columns }: { columns: ColumnDef<MachineIndicators>[] }) {
  const { t } = useI18n();
  const runs: { group: Group; span: number }[] = [];
  for (const column of columns) {
    const group = GROUP_OF[column.key];
    const last = runs[runs.length - 1];
    if (last && last.group === group) last.span += 1;
    else runs.push({ group, span: 1 });
  }
  return (
    <TableRow className="hover:bg-transparent">
      {runs.map((run, index) => (
        <TableHead
          key={`${run.group}-${index}`}
          colSpan={run.span}
          className={cn(
            "h-7 pb-0 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary",
            run.group === "maintenance" && "border-l border-border",
          )}
        >
          {run.group === "production" && (
            <span className="inline-flex items-center gap-1.5">
              <DowntimeIcon className="h-3.5 w-3.5" />
              {t("maintenance.history.production.title")}
            </span>
          )}
          {run.group === "maintenance" && (
            <span className="inline-flex items-center gap-1.5">
              <WrenchIcon className="h-3.5 w-3.5" />
              {t("maintenance.history.maintenance.title")}
            </span>
          )}
        </TableHead>
      ))}
    </TableRow>
  );
}

export function IndicatorsView({
  data,
  isLoading,
  equipmentId,
  onOpen,
}: {
  data: IndicatorsResponse | undefined;
  isLoading: boolean;
  equipmentId: string;
  onOpen: (machine: MachineIndicators) => void;
}) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const costsVisible = data?.costs_visible ?? false;
  const machines = useMemo(
    () => (data?.machines ?? []).filter((machine) => !equipmentId || machine.equipment_id === equipmentId),
    [data, equipmentId],
  );

  const totals = useMemo(
    () => ({
      production: machines.reduce((sum, m) => sum + (m.production?.breakdowns ?? 0), 0),
      maintenance: machines.reduce((sum, m) => sum + m.maintenance.breakdowns, 0),
      immobilisedHours: machines.reduce((sum, m) => sum + m.maintenance.immobilised_minutes, 0) / 60,
      cost: costsVisible ? machines.reduce((sum, m) => sum + (m.maintenance.parts_cost ?? 0), 0) : null,
    }),
    [machines, costsVisible],
  );

  const filterFields: FilterField<MachineIndicators>[] = [
    { key: "machine", kind: "text", getValue: (m) => `${m.code} ${m.name}` },
    { key: "prod_breakdowns", kind: "range", getValue: (m) => m.production?.breakdowns ?? null },
    { key: "maint_breakdowns", kind: "range", getValue: (m) => m.maintenance.breakdowns },
    { key: "cost", kind: "range", getValue: (m) => m.maintenance.parts_cost },
  ];
  const filters = useColumnFilters(filterFields);
  const rangeCell = (key: string): FilterCell => ({
    type: "range",
    min: filters.range[key]?.min ?? "",
    max: filters.range[key]?.max ?? "",
    onMinChange: (value) => filters.setRangeValue(key, "min", value),
    onMaxChange: (value) => filters.setRangeValue(key, "max", value),
  });

  const columns: ColumnDef<MachineIndicators>[] = [
    {
      key: "machine",
      header: t("maintenance.history.column.machine"),
      defaultWidth: 220,
      alwaysVisible: true,
      mobileRole: "title",
      sortValue: (m) => m.name,
      filterCell: {
        type: "text",
        value: filters.text.machine ?? "",
        onChange: (v) => filters.setTextValue("machine", v),
        placeholder: t("maintenance.history.column.machine"),
      },
      cell: (m) => (
        <span className="flex min-w-0 items-center gap-2">
          <MachineThumb machine={m} />
          <span className="min-w-0">
            <span className="block truncate font-medium">{m.name}</span>
            <span className="block truncate font-mono text-xs text-muted-foreground">{m.code}</span>
          </span>
        </span>
      ),
    },
    {
      key: "prod_breakdowns",
      header: t("maintenance.history.kpi.breakdowns"),
      defaultWidth: 100,
      sortValue: (m) => m.production?.breakdowns ?? -1,
      filterCell: rangeCell("prod_breakdowns"),
      cell: (m) => <span className="font-semibold tabular-nums">{m.production ? m.production.breakdowns : "—"}</span>,
    },
    {
      key: "prod_stop",
      header: t("maintenance.history.column.stopTime"),
      defaultWidth: 110,
      sortValue: (m) => m.production?.breakdown_minutes ?? -1,
      cell: (m) => <span className="tabular-nums">{m.production ? formatDuration(m.production.breakdown_minutes) : "—"}</span>,
    },
    {
      key: "mtbf",
      header: t("maintenance.history.kpi.mtbf"),
      defaultWidth: 110,
      sortValue: (m) => m.production?.mtbf_minutes ?? -1,
      cell: (m) => <span className="tabular-nums">{minutesOrDash(m.production?.mtbf_minutes)}</span>,
    },
    {
      key: "mttr",
      header: t("maintenance.history.kpi.mttr"),
      defaultWidth: 100,
      sortValue: (m) => m.production?.mttr_minutes ?? -1,
      cell: (m) => <span className="tabular-nums">{minutesOrDash(m.production?.mttr_minutes)}</span>,
    },
    {
      key: "maint_breakdowns",
      header: t("maintenance.history.kpi.breakdowns"),
      defaultWidth: 100,
      headerClassName: "border-l border-border",
      cellClassName: "border-l border-border",
      sortValue: (m) => m.maintenance.breakdowns,
      filterCell: rangeCell("maint_breakdowns"),
      cell: (m) => <span className="font-semibold tabular-nums">{m.maintenance.breakdowns}</span>,
    },
    {
      key: "immobilisation",
      header: t("maintenance.history.kpi.immobilisation"),
      defaultWidth: 130,
      sortValue: (m) => m.maintenance.immobilised_minutes,
      cell: (m) => <span className="tabular-nums">{formatDuration(m.maintenance.immobilised_minutes)}</span>,
    },
    {
      key: "preventive",
      header: t("maintenance.history.column.preventive"),
      defaultWidth: 150,
      sortValue: (m) => m.maintenance.preventive.overdue,
      cell: (m) => {
        const { due, closed, overdue } = m.maintenance.preventive;
        if (due === 0) return <span className="text-muted-foreground">—</span>;
        return (
          <Badge variant={overdue > 0 ? "warning" : "success"}>
            {closed}/{due}
            {overdue > 0 && ` · ${fill(t("maintenance.history.preventive.overdue"), { n: overdue })}`}
          </Badge>
        );
      },
    },
    {
      key: "technician",
      header: t("maintenance.history.column.technician"),
      defaultWidth: 110,
      sortValue: (m) => m.maintenance.technician_seconds,
      cell: (m) => <span className="tabular-nums">{formatDuration(m.maintenance.technician_seconds / 60)}</span>,
    },
    ...(costsVisible
      ? [
          {
            key: "cost",
            header: `${t("maintenance.history.kpi.partsCost")} (${CURRENCY_CODE})`,
            defaultWidth: 140,
            sortValue: (m: MachineIndicators) => m.maintenance.parts_cost ?? 0,
            filterCell: rangeCell("cost"),
            cell: (m: MachineIndicators) => (
              <span className="tabular-nums">{m.maintenance.parts_cost === null ? "—" : formatXofWithCode(m.maintenance.parts_cost)}</span>
            ),
          },
        ]
      : []),
  ];
  const table = useTableColumns("maintenance.history.indicators", columns);
  const rows = table.sortRows(filters.apply(machines));
  const span = table.visibleColumns.length;
  const empty = (
    <EmptyState
      icon={<Gauge className="h-5 w-5" />}
      illustration={<HistoryEmptyIllustration aria-hidden className="h-44 w-52" />}
      title={t("maintenance.history.indicators.empty.title")}
      description={t("maintenance.history.indicators.empty.description")}
    />
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("maintenance.history.stat.productionBreakdowns")}
          value={data?.production_available ? totals.production : null}
          icon={<DowntimeIcon className="h-5 w-5" />}
        />
        <StatCard label={t("maintenance.history.stat.maintenanceBreakdowns")} value={totals.maintenance} icon={<WrenchIcon className="h-5 w-5" />} />
        <StatCard
          label={t("maintenance.history.stat.immobilisation")}
          value={totals.immobilisedHours}
          unit="h"
          decimals={1}
          icon={<ImmobilisationIcon className="h-5 w-5" />}
          accent="warning"
        />
        {costsVisible && (
          <StatCard
            label={t("maintenance.history.stat.partsCost")}
            value={totals.cost}
            unit={CURRENCY_CODE}
            icon={<SparePartsIcon className="h-5 w-5" />}
            accent="accent"
          />
        )}
      </div>

      {isMobile ? (
        <MobileCardList
          columns={table.visibleColumns}
          rows={rows}
          rowKey={(m) => m.equipment_id}
          loading={isLoading}
          emptyIcon={<Gauge className="h-5 w-5" />}
          emptyTitle={t("maintenance.history.indicators.empty.title")}
          emptyDescription={t("maintenance.history.indicators.empty.description")}
          onRowClick={onOpen}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table colWidths={table.colWidths}>
              <TableHeader>
                <GroupRow columns={table.visibleColumns} />
                <TableRow>
                  {table.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={table.getWidth(column.key)}
                      onResize={(width) => table.setWidth(column.key, width)}
                      className={column.headerClassName}
                      sortDirection={table.sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
                <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
              </TableHeader>
              <TableBody>
                {isLoading &&
                  [0, 1, 2].map((index) => (
                    <TableRow key={`skeleton-${index}`}>
                      <TableCell colSpan={span}>
                        <Skeleton className="h-5 w-full" />
                      </TableCell>
                    </TableRow>
                  ))}
                {!isLoading && rows.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={span} className="p-0">
                      {empty}
                    </TableCell>
                  </TableRow>
                )}
                {!isLoading &&
                  rows.map((machine) => (
                    <TableRow key={machine.equipment_id} onClick={() => onOpen(machine)} className="cursor-pointer">
                      {table.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>
                          {column.cell(machine)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {data?.unattributed_stops && data.unattributed_stops.count > 0 && (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {fill(t("maintenance.history.unattributed"), {
            count: data.unattributed_stops.count,
            minutes: formatDuration(data.unattributed_stops.minutes),
          })}
        </p>
      )}
    </div>
  );
}
