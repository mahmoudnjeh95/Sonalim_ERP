import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Archive, ArchiveRestore, Building2, Factory, Eye, Pencil, Users } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useNavigate } from "react-router-dom";
import { cn } from "../../lib/utils";
import { Badge, type BadgeProps } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { activatePartner, archivePartner, createPartner, updatePartner, listPartners, type Partner, type PartnerKind } from "./api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const newPartnerSchema = z.object({
  name: z.string().min(1, "Required"),
  kind: z.enum(["customer", "supplier", "both"]),
  industry: z.string().optional(),
  website: z.string().optional(),
  phone: z.string().optional(),
  email: z.string().optional(),
});
type NewPartnerForm = z.infer<typeof newPartnerSchema>;

const PARTNERS_QUERY_KEY = ["core", "partners"] as const;

const KIND_VARIANT: Record<PartnerKind, BadgeProps["variant"]> = {
  customer: "primary",
  supplier: "warning",
  both: "accent",
};

function KindBadge({ kind }: { kind: PartnerKind }) {
  const { t } = useI18n();
  return <Badge variant={KIND_VARIANT[kind]}>{t(`partners.kind.${kind}`)}</Badge>;
}

type KindFilter = "all" | "customer" | "supplier";

export function PartnersPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingPartner, setEditingPartner] = useState<Partner | null>(null);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");

  const {
    data: partners = [],
    isLoading,
    isError: isListError,
  } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewPartnerForm>({ resolver: zodResolver(newPartnerSchema), defaultValues: { kind: "customer" } });

  const createMutation = useMutation({
    mutationFn: (input: NewPartnerForm) => createPartner(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PARTNERS_QUERY_KEY });
      setDialogOpen(false);
      reset({ kind: "customer" });
      toast.success(t("partners.created"));
    },
    onError: (error) => {
      toast.error(t("partners.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewPartnerForm) => updatePartner(token, editingPartner!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PARTNERS_QUERY_KEY });
      setDialogOpen(false);
      setEditingPartner(null);
      reset({ kind: "customer" });
      toast.success(t("partners.updated"));
    },
    onError: (error) => {
      toast.error(t("partners.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingPartner(null);
    reset({ kind: "customer", name: "", industry: "", website: "", phone: "", email: "" });
    setDialogOpen(true);
  }

  function openEditDialog(partner: Partner) {
    setEditingPartner(partner);
    reset({
      name: partner.name,
      kind: partner.kind,
      industry: partner.industry ?? "",
      website: partner.website ?? "",
      phone: partner.phone ?? "",
      email: partner.email ?? "",
    });
    setDialogOpen(true);
  }

  const archiveMutation = useMutation({
    mutationFn: (partnerId: string) => archivePartner(token, partnerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PARTNERS_QUERY_KEY });
      toast.success(t("partners.archived"));
    },
    onError: (error) => {
      toast.error(t("partners.archiveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const activateMutation = useMutation({
    mutationFn: (partnerId: string) => activatePartner(token, partnerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PARTNERS_QUERY_KEY });
      toast.success(t("partners.activated"));
    },
    onError: (error) => {
      toast.error(t("partners.activateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const customerCount = partners.filter((p) => p.kind === "customer" || p.kind === "both").length;
  const supplierCount = partners.filter((p) => p.kind === "supplier" || p.kind === "both").length;

  const filteredPartners = partners.filter((p) => {
    if (kindFilter === "all") return true;
    if (kindFilter === "customer") return p.kind === "customer" || p.kind === "both";
    return p.kind === "supplier" || p.kind === "both";
  });

  const columns: ColumnDef<Partner>[] = [
    {
      key: "name",
      header: t("partners.column.name"),
      defaultWidth: 220,
      cell: (partner) => <span className="font-medium">{partner.name}</span>,
      sortValue: (partner) => partner.name,
    },
    {
      key: "kind",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("partners.column.kind")}
          <HelpTooltip text={t("partners.help.kind")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (partner) => <KindBadge kind={partner.kind} />,
      sortValue: (partner) => partner.kind,
    },
    {
      key: "status",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("partners.column.status")}
          <HelpTooltip text={t("partners.help.status")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (partner) => <StatusBadge status={partner.status} />,
      sortValue: (partner) => partner.status,
    },
    {
      key: "action",
      header: t("partners.column.action"),
      defaultWidth: 280,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (partner) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => navigate(`/crm/partners/${partner.id}`)}>
            <Eye className="h-3.5 w-3.5" />
            View
          </Button>
          <Button size="sm" variant="outline" onClick={() => openEditDialog(partner)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("partners.edit")}
          </Button>
          {partner.status === "active" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => archiveMutation.mutate(partner.id)}
              disabled={archiveMutation.isPending && archiveMutation.variables === partner.id}
            >
              <Archive className="h-3.5 w-3.5" />
              {archiveMutation.isPending && archiveMutation.variables === partner.id
                ? t("partners.archiving")
                : t("partners.archive")}
            </Button>
          )}
          {partner.status === "archived" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => activateMutation.mutate(partner.id)}
              disabled={activateMutation.isPending && activateMutation.variables === partner.id}
            >
              <ArchiveRestore className="h-3.5 w-3.5" />
              {activateMutation.isPending && activateMutation.variables === partner.id
                ? t("partners.activating")
                : t("partners.activate")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("partners.list", columns);
  const sortedPartners = sortRows(filteredPartners);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("partners.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("partners.subtitle")}</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("partners.stat.total")} value={partners.length} icon={<Users className="h-5 w-5" />} />
        <StatCard
          label={t("partners.stat.customers")}
          value={customerCount}
          icon={<Building2 className="h-5 w-5" />}
          accent="primary"
        />
        <StatCard
          label={t("partners.stat.suppliers")}
          value={supplierCount}
          icon={<Factory className="h-5 w-5" />}
          accent="warning"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <CardTitle>{t("partners.table.title")}</CardTitle>
            <div className="inline-flex rounded-lg border border-border bg-muted/40 p-1">
              {(["all", "customer", "supplier"] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => setKindFilter(option)}
                  className={cn(
                    "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                    kindFilter === option
                      ? "bg-background text-foreground shadow-soft"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t(`partners.filter.${option}`)}
                </button>
              ))}
            </div>
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog
            open={dialogOpen}
            onOpenChange={(open) => {
              setDialogOpen(open);
              if (!open) setEditingPartner(null);
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreateDialog}>
                <Users className="h-4 w-4" />
                {t("partners.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editingPartner ? t("partners.dialog.editTitle") : t("partners.dialog.title")}</DialogTitle>
                <DialogDescription>
                  {editingPartner ? t("partners.dialog.editDescription") : t("partners.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingPartner ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="name">{t("partners.field.name")}</Label>
                    <Input id="name" {...register("name")} />
                    {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="kind">{t("partners.field.kind")}</Label>
                    <Select id="kind" {...register("kind")}>
                      <option value="customer">{t("partners.kind.customer")}</option>
                      <option value="supplier">{t("partners.kind.supplier")}</option>
                      <option value="both">{t("partners.kind.both")}</option>
                    </Select>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="email">{t("partners.field.email")}</Label>
                  <Input id="email" type="email" {...register("email")} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="industry">{t("partners.field.industry")}</Label>
                    <Input id="industry" {...register("industry")} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="phone">{t("partners.field.phone")}</Label>
                    <Input id="phone" {...register("phone")} />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="website">{t("partners.field.website")}</Label>
                  <Input id="website" {...register("website")} />
                </div>
                {(editingPartner ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingPartner ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingPartner ? updateMutation.error : createMutation.error)?.message
                      : t(editingPartner ? "partners.updateError" : "partners.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingPartner ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingPartner
                    ? updateMutation.isPending
                      ? t("partners.updating")
                      : t("partners.update")
                    : createMutation.isPending
                      ? t("partners.creating")
                      : t("partners.create")}
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
              {isLoading && <TableLoadingRow colSpan={visibleColumns.length} />}
              {isListError && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="py-8 text-center text-destructive">
                    {t("partners.loadError")}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading && !isListError && filteredPartners.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Users className="h-5 w-5" />}
                      title={t("partners.empty.title")}
                      description={t("partners.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedPartners.map((partner, i) => (
                  <PartnerRow key={partner.id} partner={partner} index={i} columns={visibleColumns} />
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function PartnerRow({ partner, index, columns }: { partner: Partner; index: number; columns: ColumnDef<Partner>[] }) {
  return (
    <motion.tr
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0, transition: { delay: Math.min(index * 0.04, 0.3) } }}
      exit={{ opacity: 0 }}
      className="border-b border-border last:border-0 hover:bg-muted/50"
    >
      {columns.map((column) => (
        <TableCell key={column.key} className={column.cellClassName}>
          {column.cell(partner)}
        </TableCell>
      ))}
    </motion.tr>
  );
}
