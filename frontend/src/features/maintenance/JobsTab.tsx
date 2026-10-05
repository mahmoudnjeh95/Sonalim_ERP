import { useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, ClipboardList, Plus, User } from "lucide-react";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { AppLoader } from "../../components/patterns/AppLoader";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { MobileCardList } from "../../components/patterns/MobileCardList";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { formatDuration } from "../../lib/units";
import { useIsMobile } from "../../lib/useIsMobile";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";
import { useEquipmentList, useJobs, type JobFilters, type JobListItem, type JobStatus } from "./api";
import { useHasPermission } from "./hooks";
import { JOB_KIND_LABEL_KEY, JOB_PRIORITY_LABEL_KEY, JOB_STATUS_BADGE_VARIANT, JOB_STATUS_LABEL_KEY } from "./labels";
import { NewJobDialog } from "./jobs/NewJobDialog";
import { apiErrorMessage, formatDay } from "./jobs/jobFormat";

type StatusFilter = "all" | "planned" | "assigned" | "in_progress" | "submitted" | "closed" | "cancelled";

/** The chips, and the job statuses each one asks the API for ("En cours" covers a job being worked, first time or in rework). */
const STATUS_FILTERS: { value: StatusFilter; labelKey: TranslationKey; statuses?: JobStatus[] }[] = [
  { value: "all", labelKey: "maintenance.jobs.filter.all" },
  { value: "planned", labelKey: "maintenance.jobs.filter.planned", statuses: ["planned"] },
  { value: "assigned", labelKey: "maintenance.jobs.filter.assigned", statuses: ["assigned"] },
  { value: "in_progress", labelKey: "maintenance.jobs.filter.inProgress", statuses: ["in_progress", "rework"] },
  { value: "submitted", labelKey: "maintenance.jobs.filter.submitted", statuses: ["submitted"] },
  { value: "closed", labelKey: "maintenance.jobs.filter.closed", statuses: ["closed"] },
  { value: "cancelled", labelKey: "maintenance.jobs.filter.cancelled", statuses: ["cancelled"] },
];

function isStatusFilter(value: string | null): value is StatusFilter {
  return STATUS_FILTERS.some((filter) => filter.value === value);
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn("block h-full rounded-full", done >= total && total > 0 ? "bg-success" : "bg-primary")} style={{ width: `${percent}%` }} />
      </span>
      <span className="text-xs tabular-nums text-muted-foreground">
        {done}/{total}
      </span>
    </div>
  );
}

/**
 * The Interventions tab: every maintenance job, filtered by status chip,
 * "Mes interventions" (jobs whose chef is the signed-in user) and machine.
 * A table on desktop, cards on a phone; a row opens the job page.
 *
 * The filters live in the URL (`?tab=jobs&status=…&mine=…&equipment=…`) so the
 * job page's back link — and a shared link — lands on the same view.
 */
export function JobsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();

  const canPlan = useHasPermission("maintenance.plan_jobs");
  const canExecute = useHasPermission("maintenance.execute_jobs");

  const statusParam = searchParams.get("status");
  const statusFilter: StatusFilter = isStatusFilter(statusParam) ? statusParam : "all";
  const mineParam = searchParams.get("mine");
  // A chef d'atelier who does not plan lands on their own jobs; anyone can flip the toggle either way.
  const mineByDefault = canExecute && !canPlan;
  const mine = mineParam === null ? mineByDefault : mineParam === "1";
  const equipmentId = searchParams.get("equipment") ?? "";

  function updateParams(patch: Record<string, string | null>) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(patch)) {
          if (value === null) next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  }

  const filters = useMemo<JobFilters>(
    () => ({
      status: STATUS_FILTERS.find((filter) => filter.value === statusFilter)?.statuses,
      equipment_id: equipmentId || undefined,
      mine: mine || undefined,
    }),
    [statusFilter, equipmentId, mine],
  );

  const { data: jobs, isLoading, isError, error } = useJobs(token, filters);
  const { data: equipment = [] } = useEquipmentList(token);
  const [newJobOpen, setNewJobOpen] = useState(false);

  // The branded loader shows once, on the tab's first load; a filter change after that uses skeleton rows.
  const loadedOnce = useRef(false);
  if (jobs) loadedOnce.current = true;
  const firstLoad = isLoading && !loadedOnce.current;

  const machines = useMemo(
    () =>
      equipment
        .filter((item) => !item.archived_at || item.id === equipmentId)
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name)),
    [equipment, equipmentId],
  );

  const columns = useMemo<ColumnDef<JobListItem>[]>(
    () => [
      {
        key: "number",
        header: t("maintenance.jobs.column.number"),
        defaultWidth: 140,
        minWidth: 120,
        alwaysVisible: true,
        // On a phone card the job's title is the headline and its number the second line.
        mobileRole: "subtitle",
        sortValue: (job) => job.number,
        cell: (job) => <span className="font-mono text-xs font-medium">{job.number}</span>,
      },
      {
        key: "title",
        header: t("maintenance.jobs.column.title"),
        defaultWidth: 240,
        minWidth: 140,
        mobileRole: "title",
        sortValue: (job) => job.title,
        cell: (job) => <span className="block truncate" title={job.title}>{job.title}</span>,
      },
      {
        key: "machine",
        header: t("maintenance.jobs.column.machine"),
        defaultWidth: 200,
        minWidth: 120,
        sortValue: (job) => job.equipment_name,
        cell: (job) => (
          <span className="block truncate" title={`${job.equipment_code} — ${job.equipment_name}`}>
            {job.equipment_name}
            <span className="ml-1.5 font-mono text-xs text-muted-foreground">{job.equipment_code}</span>
          </span>
        ),
      },
      {
        key: "type",
        header: t("maintenance.jobs.column.type"),
        defaultWidth: 190,
        minWidth: 110,
        sortValue: (job) => `${job.priority === "urgent" ? "0" : "1"}${job.kind}`,
        cell: (job) => (
          <span className="inline-flex flex-wrap items-center justify-end gap-1 md:justify-start">
            <Badge variant="outline">{t(JOB_KIND_LABEL_KEY[job.kind])}</Badge>
            {job.priority === "urgent" && (
              <Badge variant="destructive">
                <AlertTriangle className="h-3 w-3" />
                {t(JOB_PRIORITY_LABEL_KEY.urgent)}
              </Badge>
            )}
          </span>
        ),
      },
      {
        key: "status",
        header: t("maintenance.jobs.column.status"),
        defaultWidth: 140,
        minWidth: 110,
        sortValue: (job) => job.status,
        cell: (job) => (
          <Badge variant={JOB_STATUS_BADGE_VARIANT[job.status]} dot>
            {t(JOB_STATUS_LABEL_KEY[job.status])}
          </Badge>
        ),
      },
      {
        key: "due_date",
        header: t("maintenance.jobs.column.dueDate"),
        defaultWidth: 140,
        minWidth: 110,
        sortValue: (job) => job.due_date,
        cell: (job) => (
          <span
            className={cn("whitespace-nowrap", job.overdue && "font-medium text-destructive")}
            title={job.overdue ? t("maintenance.jobs.overdue") : undefined}
          >
            {formatDay(job.due_date)}
            {job.overdue && <span className="ml-1.5 text-xs">· {t("maintenance.jobs.overdue")}</span>}
          </span>
        ),
      },
      {
        key: "chef",
        header: t("maintenance.jobs.column.chef"),
        defaultWidth: 170,
        minWidth: 110,
        sortValue: (job) => job.chef_name,
        cell: (job) =>
          job.chef_name ? (
            <span className="block truncate" title={job.team_name ? `${job.chef_name} · ${job.team_name}` : job.chef_name}>
              {job.chef_name}
            </span>
          ) : (
            <span className="text-muted-foreground">{t("maintenance.jobs.noChef")}</span>
          ),
      },
      {
        key: "progress",
        header: t("maintenance.jobs.column.progress"),
        defaultWidth: 140,
        minWidth: 110,
        sortValue: (job) => (job.checks_total > 0 ? job.checks_done / job.checks_total : 0),
        cell: (job) => <ProgressBar done={job.checks_done} total={job.checks_total} />,
      },
      {
        key: "minutes",
        header: t("maintenance.jobs.column.minutes"),
        defaultWidth: 120,
        minWidth: 90,
        sortValue: (job) => job.minutes_spent,
        cell: (job) => <span className="whitespace-nowrap tabular-nums">{job.minutes_spent > 0 ? formatDuration(job.minutes_spent) : "—"}</span>,
      },
    ],
    [t],
  );

  const table = useTableColumns("maintenance.jobs", columns);
  const rows = table.sortRows(jobs ?? []);
  const span = table.visibleColumns.length;

  // Narrowed at all (drives the empty-state wording) vs. moved away from the defaults (drives "clear").
  const filtersActive = statusFilter !== "all" || !!equipmentId || mine;
  const filtersChanged = statusFilter !== "all" || !!equipmentId || mine !== mineByDefault;
  const emptyTitle = isError
    ? t("maintenance.jobs.loadError.title")
    : filtersActive
      ? t("maintenance.jobs.empty.filtered.title")
      : t("maintenance.jobs.empty.title");
  const emptyDescription = isError
    ? apiErrorMessage(error, t("maintenance.jobs.loadError.description"))
    : filtersActive
      ? t("maintenance.jobs.empty.filtered.description")
      : canPlan
        ? t("maintenance.jobs.empty.description.planner")
        : t("maintenance.jobs.empty.description");
  const emptyIcon = isError ? <AlertTriangle className="h-5 w-5" /> : <ClipboardList className="h-5 w-5" />;

  function openJob(job: JobListItem) {
    navigate(`/maintenance/jobs/${job.id}`, { state: { from: `${location.pathname}${location.search}` } });
  }

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <FilterTabs
            options={STATUS_FILTERS.map((filter) => ({ value: filter.value, label: t(filter.labelKey) }))}
            value={statusFilter}
            onChange={(value) => updateParams({ status: value === "all" ? null : value })}
          />
          {canPlan && (
            <Button className="w-full sm:w-auto" onClick={() => setNewJobOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("maintenance.jobs.new")}
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={mine ? "default" : "outline"}
            size="sm"
            aria-pressed={mine}
            onClick={() => updateParams({ mine: mine ? "0" : "1" })}
          >
            <User className="h-3.5 w-3.5" />
            {t("maintenance.jobs.filter.mine")}
          </Button>
          {machines.length > 0 && (
            // On a phone the select takes its own full-width line, after the buttons.
            <div className="order-last w-full sm:order-none sm:w-64">
              <Select
                aria-label={t("maintenance.jobs.filter.machine")}
                value={equipmentId}
                onChange={(event) => updateParams({ equipment: event.target.value || null })}
              >
                <option value="">{t("maintenance.jobs.filter.machine.all")}</option>
                {machines.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.code} — {item.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
          {filtersChanged && (
            <Button variant="ghost" size="sm" onClick={() => updateParams({ status: null, equipment: null, mine: null })}>
              {t("common.clearFilters")}
            </Button>
          )}
          {!isMobile && (
            <div className="ml-auto">
              <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
            </div>
          )}
        </div>
      </div>

      {firstLoad ? (
        <AppLoader className="py-16" />
      ) : isMobile ? (
        <MobileCardList
          columns={table.visibleColumns}
          rows={rows}
          rowKey={(job) => job.id}
          loading={isLoading}
          emptyIcon={emptyIcon}
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
          onRowClick={openJob}
          rowClassName={(job) => (job.priority === "urgent" ? "border-l-4 border-l-destructive" : undefined)}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table colWidths={table.colWidths}>
              <TableHeader>
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
                      <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
                    </TableCell>
                  </TableRow>
                )}
                {!isLoading &&
                  rows.map((job) => (
                    <TableRow
                      key={job.id}
                      onClick={() => openJob(job)}
                      className={cn("cursor-pointer", job.priority === "urgent" && "shadow-[inset_3px_0_0_0_hsl(0_72%_51%)]")}
                    >
                      {table.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>
                          {column.cell(job)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {canPlan && <NewJobDialog open={newJobOpen} onOpenChange={setNewJobOpen} />}
    </div>
  );
}
