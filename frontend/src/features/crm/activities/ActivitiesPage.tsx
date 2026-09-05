import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Check, ClipboardList, MessageSquare, Phone, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
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
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import {
  completeActivity,
  createActivity,
  listActivities,
  type Activity,
  type ActivityKind,
  type ActivitySubjectType,
} from "./api";

const ACTIVITIES_QUERY_KEY = ["crm", "activities"] as const;

type ActivityFilter = "all" | ActivityKind | "open" | "overdue" | "completed";

const KIND_ICON = { comment: MessageSquare, task: ClipboardList, call: Phone };

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "-";
}

export function ActivitiesPage() {
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [kind, setKind] = useState<ActivityKind>("task");
  const [subjectType, setSubjectType] = useState<ActivitySubjectType>("lead");
  const [subjectId, setSubjectId] = useState("");
  const [note, setNote] = useState("");
  const [dueAt, setDueAt] = useState("");

  const { data: activities = [], isLoading, isError } = useQuery({
    queryKey: ACTIVITIES_QUERY_KEY,
    queryFn: () => listActivities(token),
  });

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
      toast.success("Activity logged");
    },
    onError: (error) => toast.error("Could not log activity", { description: error instanceof ApiError ? error.message : undefined }),
  });

  const completeMutation = useMutation({
    mutationFn: (activityId: string) => completeActivity(token, activityId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACTIVITIES_QUERY_KEY });
      toast.success("Activity completed");
    },
    onError: (error) => toast.error("Could not complete activity", { description: error instanceof ApiError ? error.message : undefined }),
  });

  const filteredActivities = activities.filter((activity) => {
    if (filter === "open") return !activity.completed_at;
    if (filter === "overdue") return !activity.completed_at && Boolean(activity.due_at) && new Date(activity.due_at!).getTime() < Date.now();
    if (filter === "completed") return Boolean(activity.completed_at);
    return filter === "all" || activity.kind === filter;
  });

  const columns: ColumnDef<Activity>[] = [
    {
      key: "kind",
      header: "Type",
      defaultWidth: 140,
      cell: (activity) => {
        const Icon = KIND_ICON[activity.kind];
        return (
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-muted-foreground" />
            <StatusBadge status={activity.kind} />
          </div>
        );
      },
      sortValue: (activity) => activity.kind,
    },
    {
      key: "note",
      header: "Note",
      defaultWidth: 260,
      cellClassName: "max-w-sm truncate",
      cell: (activity) => activity.note,
      sortValue: (activity) => activity.note,
    },
    {
      key: "record",
      header: "Record",
      defaultWidth: 200,
      cell: (activity) => (
        <>
          <span className="text-xs text-muted-foreground">{activity.subject_type}</span>
          <br />
          {activity.subject_id}
        </>
      ),
    },
    {
      key: "due",
      header: "Due",
      defaultWidth: 160,
      cell: (activity) => formatDate(activity.due_at),
      sortValue: (activity) => activity.due_at,
    },
    {
      key: "status",
      header: "Status",
      defaultWidth: 140,
      cell: (activity) => (activity.completed_at ? <StatusBadge status="completed" /> : <StatusBadge status="in_progress" />),
      sortValue: (activity) => (activity.completed_at ? "completed" : "in_progress"),
    },
    {
      key: "action",
      header: "Action",
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (activity) =>
        !activity.completed_at && (
          <Button variant="ghost" size="sm" onClick={() => completeMutation.mutate(activity.id)}>
            <Check className="h-4 w-4" />
            Complete
          </Button>
        ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("crm.activities", columns);
  const sortedActivities = sortRows(filteredActivities);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Agenda</h1>
          <p className="text-sm text-muted-foreground">Calls, tasks, and notes across your CRM.</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button><Plus className="h-4 w-4" />Log activity</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Log activity</DialogTitle>
              <DialogDescription>Record a call, task, or note against a CRM record.</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); createMutation.mutate(); }}>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5"><Label htmlFor="activity-kind">Type</Label><Select id="activity-kind" value={kind} onChange={(event) => setKind(event.target.value as ActivityKind)}><option value="task">Task</option><option value="call">Call</option><option value="comment">Note</option></Select></div>
                <div className="space-y-1.5"><Label htmlFor="activity-subject-type">Record type</Label><Select id="activity-subject-type" value={subjectType} onChange={(event) => setSubjectType(event.target.value as ActivitySubjectType)}><option value="lead">Lead</option><option value="partner">Account</option><option value="opportunity">Opportunity</option></Select></div>
              </div>
              <div className="space-y-1.5"><Label htmlFor="activity-subject-id">Record ID</Label><Input id="activity-subject-id" required value={subjectId} onChange={(event) => setSubjectId(event.target.value)} placeholder="Paste the lead, account, or opportunity ID" /></div>
              <div className="space-y-1.5"><Label htmlFor="activity-note">Note</Label><Input id="activity-note" required value={note} onChange={(event) => setNote(event.target.value)} placeholder="What needs to be remembered?" /></div>
              <div className="space-y-1.5"><Label htmlFor="activity-due">Due date</Label><Input id="activity-due" type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></div>
              <Button type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? "Logging..." : "Log activity"}</Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Activity timeline</CardTitle>
          <div className="flex flex-wrap items-center gap-3">
            <FilterTabs value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "open", label: "Open" }, { value: "overdue", label: "Overdue" }, { value: "task", label: "Tasks" }, { value: "call", label: "Calls" }, { value: "comment", label: "Notes" }, { value: "completed", label: "Completed" }]} />
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
        </CardHeader>
        <CardContent>
          {isError && <p className="py-8 text-center text-sm text-destructive">Could not load activities.</p>}
          {!isError && !isLoading && filteredActivities.length === 0 && <EmptyState icon={<CalendarDays className="h-5 w-5" />} title="No activities" description="Log your first CRM activity to start the timeline." />}
          {isLoading && <p className="py-8 text-center text-sm text-muted-foreground">Loading activities...</p>}
          {!isError && filteredActivities.length > 0 && (
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
    </div>
  );
}
