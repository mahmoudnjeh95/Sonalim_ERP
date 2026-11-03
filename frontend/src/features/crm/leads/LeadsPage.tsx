import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRightCircle, Ban, Contact, Pencil, Plus, UserCheck, Users } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
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
import { HelpTooltip } from "../../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { listPartners } from "../../partners/api";
import { TableLoadingRow } from "../../../components/patterns/AppLoader";
import {
  convertLead,
  createLead,
  disqualifyLead,
  LEAD_SOURCES,
  listLeads,
  qualifyLead,
  updateLead,
  type Lead,
  type Priority,
} from "./api";

const newLeadSchema = z.object({
  contact_name: z.string().min(1, "Required"),
  email: z.string().email("Enter a valid email"),
  source: z.string().optional(),
  owner_id: z.string().optional(),
  priority: z.enum(["low", "medium", "high"]),
});
type NewLeadForm = z.infer<typeof newLeadSchema>;

const LEADS_QUERY_KEY = ["crm", "leads"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;
type StatusFilter = "all" | "new" | "qualified" | "converted" | "disqualified";

export function LeadsPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingLead, setEditingLead] = useState<Lead | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [mineOnly, setMineOnly] = useState(false);
  const [duplicateEmail, setDuplicateEmail] = useState(false);
  const [disqualifyingLead, setDisqualifyingLead] = useState<Lead | null>(null);
  const [disqualifyReason, setDisqualifyReason] = useState("");
  const [convertingLead, setConvertingLead] = useState<Lead | null>(null);
  const [convertExistingPartnerId, setConvertExistingPartnerId] = useState("");

  const {
    data: leads = [],
    isLoading,
    isError: isListError,
  } = useQuery({
    queryKey: LEADS_QUERY_KEY,
    queryFn: () => listLeads(token),
  });

  const { data: users = [] } = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const activePartners = partners.filter((p) => p.status === "active" && p.kind !== "supplier");
  const ownerName = (ownerId: string | null) => {
    if (!ownerId) return t("crm.leads.unassigned");
    const user = users.find((u) => u.id === ownerId);
    return user ? userDisplayName(user) : ownerId;
  };

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewLeadForm>({ resolver: zodResolver(newLeadSchema), defaultValues: { priority: "medium" } });

  const createMutation = useMutation({
    mutationFn: (input: NewLeadForm) => createLead(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      setDialogOpen(false);
      reset({ priority: "medium" });
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
      reset({ priority: "medium" });
      toast.success(t("crm.leads.updated"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingLead(null);
    setDuplicateEmail(false);
    reset({ contact_name: "", email: "", source: "", owner_id: "", priority: "medium" });
    setDialogOpen(true);
  }

  function openEditDialog(lead: Lead) {
    setEditingLead(lead);
    setDuplicateEmail(false);
    reset({
      contact_name: lead.contact_name,
      email: lead.email,
      source: lead.source ?? "",
      owner_id: lead.owner_id ?? "",
      priority: lead.priority,
    });
    setDialogOpen(true);
  }

  function checkDuplicateEmail(email: string) {
    const normalized = email.trim().toLowerCase();
    if (!normalized) {
      setDuplicateEmail(false);
      return;
    }
    const match = leads.some((l) => l.id !== editingLead?.id && l.email.toLowerCase() === normalized);
    setDuplicateEmail(match);
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

  const disqualifyMutation = useMutation({
    mutationFn: ({ leadId, reason }: { leadId: string; reason: string }) => disqualifyLead(token, leadId, reason, crypto.randomUUID()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      setDisqualifyingLead(null);
      setDisqualifyReason("");
      toast.success(t("crm.leads.disqualifiedToast"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.disqualifyError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const convertMutation = useMutation({
    mutationFn: ({ leadId, existingPartnerId }: { leadId: string; existingPartnerId?: string }) =>
      convertLead(token, leadId, crypto.randomUUID(), existingPartnerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LEADS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["core", "partners"] });
      queryClient.invalidateQueries({ queryKey: ["crm", "opportunities"] });
      setConvertingLead(null);
      setConvertExistingPartnerId("");
      toast.success(t("crm.leads.convertedToast"));
    },
    onError: (error) => {
      toast.error(t("crm.leads.convertError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const qualifiedCount = leads.filter((l) => l.status === "qualified").length;
  const newCount = leads.filter((l) => l.status === "new").length;
  const statusFilteredLeads = statusFilter === "all" ? leads : leads.filter((l) => l.status === statusFilter);
  const mineFilteredLeads = mineOnly ? statusFilteredLeads.filter((l) => l.owner_id === session!.userId) : statusFilteredLeads;

  const columnFilterFields: FilterField<Lead>[] = [
    { key: "contact_name", kind: "text", getValue: (l) => l.contact_name },
    { key: "email", kind: "text", getValue: (l) => l.email },
    { key: "owner", kind: "text", getValue: (l) => ownerName(l.owner_id) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredLeads = columnFilters.apply(mineFilteredLeads);

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
      sortValue: (lead) => lead.contact_name,
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
      sortValue: (lead) => lead.email,
    },
    {
      key: "source",
      header: t("crm.leads.column.source"),
      defaultWidth: 140,
      cell: (lead) => (
        <span className="text-muted-foreground">
          {lead.source ? t(`crm.leads.source.${lead.source}` as Parameters<typeof t>[0]) : "—"}
        </span>
      ),
      sortValue: (lead) => lead.source ?? "",
    },
    {
      key: "owner",
      header: t("crm.leads.column.owner"),
      defaultWidth: 160,
      cell: (lead) => <span className="text-muted-foreground">{ownerName(lead.owner_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.owner ?? "",
        onChange: (v) => columnFilters.setTextValue("owner", v),
        placeholder: t("crm.leads.column.owner"),
      },
      sortValue: (lead) => ownerName(lead.owner_id),
    },
    {
      key: "priority",
      header: t("crm.leads.column.priority"),
      defaultWidth: 110,
      cell: (lead) => <span>{t(`priority.${lead.priority}` as Parameters<typeof t>[0])}</span>,
      sortValue: (lead) => lead.priority,
    },
    {
      key: "status",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("crm.leads.column.status")}
          <HelpTooltip text={t("crm.leads.help.status")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (lead) => <StatusBadge status={lead.status} />,
      sortValue: (lead) => lead.status,
    },
    {
      key: "action",
      header: t("crm.leads.column.action"),
      defaultWidth: 280,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right space-x-2",
      cell: (lead) => (
        <>
          <Button size="sm" variant="outline" onClick={() => openEditDialog(lead)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("crm.leads.edit")}
          </Button>
          {(lead.status === "new" || lead.status === "qualified") && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDisqualifyingLead(lead);
                setDisqualifyReason("");
              }}
            >
              <Ban className="h-3.5 w-3.5" />
              {t("crm.leads.disqualify")}
            </Button>
          )}
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
              onClick={() => {
                setConvertingLead(lead);
                setConvertExistingPartnerId("");
              }}
            >
              <ArrowRightCircle className="h-3.5 w-3.5" />
              {t("crm.leads.convert")}
            </Button>
          )}
        </>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("crm.leads", columns);
  const sortedLeads = sortRows(filteredLeads);

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
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("crm.leads.table.title")}</CardTitle>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "new", label: t("status.new") },
                { value: "qualified", label: t("status.qualified") },
                { value: "converted", label: t("status.converted") },
                { value: "disqualified", label: t("status.disqualified") },
              ]}
            />
            <Button variant={mineOnly ? "default" : "outline"} size="sm" onClick={() => setMineOnly((v) => !v)}>
              {t("crm.leads.filter.mine")}
            </Button>
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
                  <Input id="email" type="email" {...register("email")} onBlur={(e) => checkDuplicateEmail(e.target.value)} />
                  {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
                  {!errors.email && duplicateEmail && <p className="text-sm text-warning">{t("crm.leads.duplicateEmailWarning")}</p>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="source">{t("crm.leads.field.source")}</Label>
                    <Select id="source" {...register("source")}>
                      <option value="">—</option>
                      {LEAD_SOURCES.map((source) => (
                        <option key={source} value={source}>
                          {t(`crm.leads.source.${source}` as Parameters<typeof t>[0])}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="priority">{t("crm.leads.field.priority")}</Label>
                    <Select id="priority" {...register("priority")}>
                      {(["low", "medium", "high"] as Priority[]).map((priority) => (
                        <option key={priority} value={priority}>
                          {t(`priority.${priority}` as Parameters<typeof t>[0])}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="owner_id">{t("crm.leads.field.owner")}</Label>
                  <Select id="owner_id" {...register("owner_id")}>
                    <option value="">{t("crm.leads.unassigned")}</option>
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {userDisplayName(user)}
                      </option>
                    ))}
                  </Select>
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
              {isLoading && <TableLoadingRow colSpan={visibleColumns.length} />}
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
                {sortedLeads.map((lead, i) => (
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

      <Dialog open={disqualifyingLead !== null} onOpenChange={(open) => !open && setDisqualifyingLead(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("crm.leads.dialog.disqualifyTitle")}</DialogTitle>
            <DialogDescription>{t("crm.leads.dialog.disqualifyDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (disqualifyingLead) disqualifyMutation.mutate({ leadId: disqualifyingLead.id, reason: disqualifyReason });
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="disqualify-reason">{t("crm.leads.field.reason")}</Label>
              <Input id="disqualify-reason" required value={disqualifyReason} onChange={(e) => setDisqualifyReason(e.target.value)} />
            </div>
            <Button type="submit" className="w-full" disabled={disqualifyMutation.isPending}>
              {disqualifyMutation.isPending ? t("crm.leads.disqualifying") : t("crm.leads.disqualify")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={convertingLead !== null} onOpenChange={(open) => !open && setConvertingLead(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("crm.leads.convertDialog.title")}</DialogTitle>
            <DialogDescription>{t("crm.leads.convertDialog.description")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (convertingLead) {
                convertMutation.mutate({ leadId: convertingLead.id, existingPartnerId: convertExistingPartnerId || undefined });
              }
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="convert-existing-partner">{t("crm.leads.convertDialog.existingAccount")}</Label>
              <Select
                id="convert-existing-partner"
                value={convertExistingPartnerId}
                onChange={(e) => setConvertExistingPartnerId(e.target.value)}
              >
                <option value="">{t("crm.leads.convertDialog.createNew")}</option>
                {activePartners.map((partner) => (
                  <option key={partner.id} value={partner.id}>
                    {partner.name}
                  </option>
                ))}
              </Select>
            </div>
            <Button type="submit" className="w-full" disabled={convertMutation.isPending}>
              {convertMutation.isPending ? t("crm.leads.converting") : t("crm.leads.convertDialog.confirm")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
