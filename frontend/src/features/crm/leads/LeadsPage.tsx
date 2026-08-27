import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRightCircle, Contact, Pencil, Plus, UserCheck, Users } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
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
import { convertLead, createLead, listLeads, qualifyLead, updateLead, type Lead } from "./api";

const newLeadSchema = z.object({
  contact_name: z.string().min(1, "Required"),
  email: z.string().email("Enter a valid email"),
});
type NewLeadForm = z.infer<typeof newLeadSchema>;

const LEADS_QUERY_KEY = ["crm", "leads"] as const;
type StatusFilter = "all" | "new" | "qualified" | "converted";

export function LeadsPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingLead, setEditingLead] = useState<Lead | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const {
    data: leads = [],
    isLoading,
    isError: isListError,
  } = useQuery({
    queryKey: LEADS_QUERY_KEY,
    queryFn: () => listLeads(token),
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewLeadForm>({ resolver: zodResolver(newLeadSchema) });

  const createMutation = useMutation({
    mutationFn: (input: NewLeadForm) => createLead(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      setDialogOpen(false);
      reset();
      toast.success(t("crm.leads.created"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewLeadForm) => updateLead(token, editingLead!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      setDialogOpen(false);
      setEditingLead(null);
      reset();
      toast.success(t("crm.leads.updated"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingLead(null);
    reset({ contact_name: "", email: "" });
    setDialogOpen(true);
  }

  function openEditDialog(lead: Lead) {
    setEditingLead(lead);
    reset({ contact_name: lead.contact_name, email: lead.email });
    setDialogOpen(true);
  }

  const qualifyMutation = useMutation({
    mutationFn: (leadId: string) => qualifyLead(token, leadId, crypto.randomUUID()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      toast.success(t("crm.leads.qualifiedToast"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.qualifyError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const convertMutation = useMutation({
    mutationFn: (leadId: string) => convertLead(token, leadId, crypto.randomUUID()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["core", "partners"] });
      queryClient.invalidateQueries({ queryKey: ["crm", "opportunities"] });
      toast.success(t("crm.leads.convertedToast"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.convertError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const qualifiedCount = leads.filter((l) => l.status === "qualified").length;
  const newCount = leads.filter((l) => l.status === "new").length;
  const statusFilteredLeads = statusFilter === "all" ? leads : leads.filter((l) => l.status === statusFilter);

  const columnFilterFields: FilterField<Lead>[] = [
    { key: "contact_name", kind: "text", getValue: (l) => l.contact_name },
    { key: "email", kind: "text", getValue: (l) => l.email },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredLeads = columnFilters.apply(statusFilteredLeads);

  const columns: ColumnDef<Lead>[] = [
    {
      key: "contact_name",
      header: t("crm.leads.column.contact"),
      defaultWidth: 200,
      cell: (lead) => <span className="font-medium">{lead.contact_name}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.contact_name ?? "",
        onChange: (v) => columnFilters.setTextValue("contact_name", v),
        placeholder: t("crm.leads.column.contact"),
      },
    },
    {
      key: "email",
      header: t("crm.leads.column.email"),
      defaultWidth: 220,
      cell: (lead) => <span className="text-muted-foreground">{lead.email}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.email ?? "",
        onChange: (v) => columnFilters.setTextValue("email", v),
        placeholder: t("crm.leads.column.email"),
      },
    },
    { key: "status", header: t("crm.leads.column.status"), defaultWidth: 140, cell: (lead) => <StatusBadge status={lead.status} /> },
    {
      key: "action",
      header: t("crm.leads.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right space-x-2",
      cell: (lead) => (
        <>
          <Button size="sm" variant="outline" onClick={() => openEditDialog(lead)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("crm.leads.edit")}
          </Button>
          {lead.status === "new" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => qualifyMutation.mutate(lead.id)}
              disabled={qualifyMutation.isPending && qualifyMutation.variables === lead.id}
            >
              {qualifyMutation.isPending && qualifyMutation.variables === lead.id ? t("crm.leads.qualifying") : t("crm.leads.qualify")}
            </Button>
          )}
          {lead.status === "qualified" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => convertMutation.mutate(lead.id)}
              disabled={convertMutation.isPending && convertMutation.variables === lead.id}
            >
              <ArrowRightCircle className="h-3.5 w-3.5" />
              {convertMutation.isPending && convertMutation.variables === lead.id ? t("crm.leads.converting") : t("crm.leads.convert")}
            </Button>
          )}
        </>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "crm.leads",
    columns,
  );

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("crm.leads.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("crm.leads.subtitle")}</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("crm.leads.stat.total")} value={leads.length} icon={<Users className="h-5 w-5" />} />
        <StatCard label={t("crm.leads.stat.new")} value={newCount} icon={<Contact className="h-5 w-5" />} accent="warning" />
        <StatCard
          label={t("crm.leads.stat.qualified")}
          value={qualifiedCount}
          icon={<UserCheck className="h-5 w-5" />}
          accent="success"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <CardTitle>{t("crm.leads.table.title")}</CardTitle>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "new", label: t("status.new") },
                { value: "qualified", label: t("status.qualified") },
                { value: "converted", label: t("status.converted") },
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
              if (!open) setEditingLead(null);
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreateDialog}>
                <Plus className="h-4 w-4" />
                {t("crm.leads.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editingLead ? t("crm.leads.dialog.editTitle") : t("crm.leads.dialog.title")}</DialogTitle>
                <DialogDescription>
                  {editingLead ? t("crm.leads.dialog.editDescription") : t("crm.leads.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingLead ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="contact_name">{t("crm.leads.field.contactName")}</Label>
                  <Input id="contact_name" {...register("contact_name")} />
                  {errors.contact_name && <p className="text-sm text-destructive">{errors.contact_name.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="email">{t("crm.leads.field.email")}</Label>
                  <Input id="email" type="email" {...register("email")} />
                  {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
                </div>
                {(editingLead ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingLead ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingLead ? updateMutation.error : createMutation.error)?.message
                      : t(editingLead ? "crm.leads.updateError" : "crm.leads.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingLead ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingLead
                    ? updateMutation.isPending
                      ? t("crm.leads.updating")
                      : t("crm.leads.update")
                    : createMutation.isPending
                      ? t("crm.leads.creating")
                      : t("crm.leads.create")}
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
                    {t("crm.leads.loadError")}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading && !isListError && filteredLeads.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Contact className="h-5 w-5" />}
                      title={t("crm.leads.empty.title")}
                      description={t("crm.leads.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredLeads.map((lead, i) => (
                  <motion.tr
                    key={lead.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(lead)}
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
