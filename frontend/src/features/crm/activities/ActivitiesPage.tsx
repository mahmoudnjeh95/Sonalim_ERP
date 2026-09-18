import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Check, ClipboardList, MessageSquare, Pencil, Phone, Plus, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../../../components/ui/dialog";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { StatusBadge } from "../../../components/patterns/StatusBadge";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { ActivityKindBadge } from "../../../components/patterns/ActivityKindBadge";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { listLeads } from "../leads/api";
import { listPartners } from "../../partners/api";
import { listOpportunities } from "../opportunities/api";
import {
  completeActivity,
  createActivity,
  listActivities,
  updateActivity,
  type Activity,
  type ActivityKind,
  type ActivitySubjectType,
} from "./api";

const ACTIVITIES_QUERY_KEY = ["crm", "activities"] as const;

type ActivityFilter = "all" | ActivityKind | "open" | "overdue" | "completed";

const KIND_ICON: Record<ActivityKind, typeof MessageSquare> = { comment: MessageSquare, task: ClipboardList, call: Phone, meeting: Users };

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "-";
}

export function ActivitiesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [kind, setKind] = useState<ActivityKind>("task");
  const [subjectType, setSubjectType] = useState<ActivitySubjectType>("lead");
  const [subjectId, setSubjectId] = useState("");
  const [note, setNote] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [editingActivity, setEditingActivity] = useState<Activity | null>(null);
  const [editNote, setEditNote] = useState("");
  const [editDueAt, setEditDueAt] = useState("");

  const { data: activities = [], isLoading, isError } = useQuery({
    queryKey: ACTIVITIES_QUERY_KEY,
    queryFn: () => listActivities(token),
  });
  const { data: leads = [] } = useQuery({ queryKey: ["crm", "leads"], queryFn: () => listLeads(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: opportunities = [] } = useQuery({ queryKey: ["crm", "opportunities"], queryFn: () => listOpportunities(token) });

  const subjectOptions: Record<ActivitySubjectType, { id: string; label: string }[]> = {
    lead: leads.map((l) => ({ id: l.id, label: l.contact_name })),
    partner: partners.map((p) => ({ id: p.id, label: p.name })),
    opportunity: opportunities.map((o) => ({ id: o.id, label: o.name })),
  };

  function subjectLabel(type: ActivitySubjectType, id: string) {
    return subjectOptions[type].find((option) => option.id === id)?.label ?? id;
  }

  const createMutation = useMutation({
    mutationFn: () => createActivity(token, {
      kind,
      subject_type: subjectType,
      subject_id: subjectId,
      note,
      due_at: dueAt ? new Date(dueAt).toISOString() : undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACTIVITIES_QUERY_KEY });
      setDialogOpen(false);
      setSubjectId("");
      setNote("");
      setDueAt("");
      toast.success(t("crm.activities.created"));
    },
    onError: (error) => toast.error(t("crm.activities.createError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const completeMutation = useMutation({
    mutationFn: (activityId: string) => completeActivity(token, activityId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACTIVITIES_QUERY_KEY });
      toast.success(t("crm.activities.completedToast"));
    },
    onError: (error) => toast.error(t("crm.activities.completeError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateActivity(token, editingActivity!.id, {
        note: editNote,
        due_at: editDueAt ? new Date(editDueAt).toISOString() : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACTIVITIES_QUERY_KEY });
      setEditingActivity(null);
      toast.success(t("crm.activities.updated"));
    },
    onError: (error) => toast.error(t("crm.activities.updateError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  function openEditDialog(activity: Activity) {
    setEditingActivity(activity);
    setEditNote(activity.note);
    setEditDueAt(activity.due_at ? activity.due_at.slice(0, 16) : "");
  }

  const filteredActivities = activities.filter((activity) => {
    if (filter === "open") return !activity.completed_at;
    if (filter === "overdue") return !activity.completed_at && Boolean(activity.due_at) && new Date(activity.due_at!).getTime() < Date.now();
    if (filter === "completed") return Boolean(activity.completed_at);
    return filter === "all" || activity.kind === filter;
  });

  const columnFilterFields: FilterField<Activity>[] = [
    { key: "note", kind: "text", getValue: (a) => a.note },
    { key: "record", kind: "text", getValue: (a) => subjectLabel(a.subject_type, a.subject_id) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const columnFilteredActivities = columnFilters.apply(filteredActivities);

  const columns: ColumnDef<Activity>[] = [
    {
      key: "kind",
      header: t("crm.activities.column.type"),
      defaultWidth: 140,
      cell: (activity) => {
        const Icon = KIND_ICON[activity.kind];
        return (
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-muted-foreground" />
            <ActivityKindBadge kind={activity.kind} />
          </div>
        );
      },
      sortValue: (activity) => activity.kind,
    },
    {
      key: "note",
      header: t("crm.activities.column.note"),
      defaultWidth: 260,
      cellClassName: "max-w-sm truncate",
      cell: (activity) => activity.note,
      filterCell: {
        type: "text",
        value: columnFilters.text.note ?? "",
        onChange: (v) => columnFilters.setTextValue("note", v),
        placeholder: t("crm.activities.column.note"),
      },
      sortValue: (activity) => activity.note,
    },
    {
      key: "record",
      header: t("crm.activities.column.record"),
      defaultWidth: 200,
      cell: (activity) => (
        <>
          <span className="text-xs text-muted-foreground">{t(`crm.activity.subject.${activity.subject_type}` as Parameters<typeof t>[0])}</span>
          <br />
          {subjectLabel(activity.subject_type, activity.subject_id)}
        </>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.record ?? "",
        onChange: (v) => columnFilters.setTextValue("record", v),
        placeholder: t("crm.activities.column.record"),
      },
      sortValue: (activity) => subjectLabel(activity.subject_type, activity.subject_id),
    },
    {
      key: "due",
      header: t("crm.activities.column.due"),
      defaultWidth: 160,
      cell: (activity) => formatDate(activity.due_at),
      sortValue: (activity) => activity.due_at,
    },
    {
      key: "status",
      header: t("crm.activities.column.status"),
      defaultWidth: 140,
      cell: (activity) => (activity.completed_at ? <StatusBadge status="completed" /> : <StatusBadge status="in_progress" />),
      sortValue: (activity) => (activity.completed_at ? "completed" : "in_progress"),
    },
    {
      key: "action",
      header: t("crm.activities.column.action"),
      defaultWidth: 180,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right space-x-2",
      cell: (activity) =>
        !activity.completed_at && (
          <>
            <Button variant="ghost" size="sm" onClick={() => openEditDialog(activity)}>
              <Pencil className="h-4 w-4" />
              {t("crm.activities.edit")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => completeMutation.mutate(activity.id)}>
              <Check className="h-4 w-4" />
              {t("crm.activities.complete")}
            </Button>
          </>
        ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("crm.activities", columns);
  const sortedActivities = sortRows(columnFilteredActivities);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("crm.activities.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("crm.activities.subtitle")}</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4" />
              {t("crm.activities.new")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("crm.activities.dialog.title")}</DialogTitle>
              <DialogDescription>{t("crm.activities.dialog.description")}</DialogDescription>
            </DialogHeader>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                createMutation.mutate();
              }}
            >
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="activity-kind">{t("crm.activities.field.kind")}</Label>
                  <Select id="activity-kind" value={kind} onChange={(event) => setKind(event.target.value as ActivityKind)}>
                    <option value="task">{t("crm.activity.kind.task")}</option>
                    <option value="call">{t("crm.activity.kind.call")}</option>
                    <option value="meeting">{t("crm.activity.kind.meeting")}</option>
                    <option value="comment">{t("crm.activity.kind.comment")}</option>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="activity-subject-type">{t("crm.activities.field.subjectType")}</Label>
                  <Select
                    id="activity-subject-type"
                    value={subjectType}
                    onChange={(event) => {
                      setSubjectType(event.target.value as ActivitySubjectType);
                      setSubjectId("");
                    }}
                  >
                    <option value="lead">{t("crm.activity.subject.lead")}</option>
                    <option value="partner">{t("crm.activity.subject.account")}</option>
                    <option value="opportunity">{t("crm.activity.subject.opportunity")}</option>
                  </Select>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="activity-subject-id">{t("crm.activities.field.subject")}</Label>
                <Select id="activity-subject-id" required value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
                  <option value="">{t("crm.activities.field.subjectPlaceholder")}</option>
                  {subjectOptions[subjectType].map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="activity-note">{t("crm.activities.field.note")}</Label>
                <Input
                  id="activity-note"
                  required
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder={t("crm.activities.field.notePlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="activity-due">{t("crm.activities.field.dueDate")}</Label>
                <Input id="activity-due" type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
              </div>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? t("crm.activities.logging") : t("crm.activities.log")}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>{t("crm.activities.table.title")}</CardTitle>
          <div className="flex flex-wrap items-center gap-3">
            <FilterTabs
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "open", label: t("crm.activities.filter.open") },
                { value: "overdue", label: t("crm.activities.filter.overdue") },
                { value: "task", label: t("crm.activity.kind.task") },
                { value: "call", label: t("crm.activity.kind.call") },
                { value: "meeting", label: t("crm.activity.kind.meeting") },
                { value: "comment", label: t("crm.activity.kind.comment") },
                { value: "completed", label: t("crm.activities.filter.completed") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
        </CardHeader>
        <CardContent>
          {isError && <p className="py-8 text-center text-sm text-destructive">{t("crm.activities.loadError")}</p>}
          {!isError && !isLoading && columnFilteredActivities.length === 0 && (
            <EmptyState icon={<CalendarDays className="h-5 w-5" />} title={t("crm.activities.empty.title")} description={t("crm.activities.empty.description")} />
          )}
          {isLoading && <AppLoader label={t("crm.activities.loading")} className="py-8" />}
          {!isError && columnFilteredActivities.length > 0 && (
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
                {sortedActivities.map((activity) => (
                  <TableRow key={activity.id}>
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(activity)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={editingActivity !== null} onOpenChange={(open) => !open && setEditingActivity(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("crm.activities.dialog.editTitle")}</DialogTitle>
            <DialogDescription>{t("crm.activities.dialog.editDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              updateMutation.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="edit-activity-note">{t("crm.activities.field.note")}</Label>
              <Input id="edit-activity-note" required value={editNote} onChange={(event) => setEditNote(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-activity-due">{t("crm.activities.field.dueDate")}</Label>
              <Input id="edit-activity-due" type="datetime-local" value={editDueAt} onChange={(event) => setEditDueAt(event.target.value)} />
            </div>
            <Button type="submit" className="w-full" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? t("crm.activities.updating") : t("crm.activities.update")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
