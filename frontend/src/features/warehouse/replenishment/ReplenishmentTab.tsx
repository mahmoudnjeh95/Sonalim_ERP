import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { ProductSelect } from "../../../components/patterns/ProductSelect";
import { useProductCatalog } from "../../products/catalog";
import { listPartners } from "../../partners/api";
import { listSites } from "../locations/api";
import {
  approveProposal,
  createReorderRule,
  deleteReorderRule,
  dismissProposal,
  evaluateReplenishment,
  listProposals,
  listReorderRules,
  updateReorderRule,
  PROPOSALS_QUERY_KEY,
  REORDER_RULES_QUERY_KEY,
  type ProposalStatus,
  type ReorderRule,
  type ReplenishmentProposal,
} from "./api";

const PARTNERS_QUERY_KEY = ["core", "partners"] as const;

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function useLookups() {
  const { session } = useAuth();
  const token = session!.token;
  const { products, catalog } = useProductCatalog();
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const { data: sites = [] } = useQuery({ queryKey: ["warehouse", "sites"], queryFn: () => listSites(token) });
  const suppliers = partners.filter((p) => p.kind === "supplier" || p.kind === "both");
  return {
    catalog,
    suppliers,
    sites,
    productName: (id: string) => products.find((p) => p.id === id)?.name ?? id,
    supplierName: (id: string | null) => (id ? (partners.find((p) => p.id === id)?.name ?? id) : "—"),
    siteName: (id: string | null) => (id ? (sites.find((s) => s.id === id)?.name ?? id) : null),
  };
}

function RuleDialog({ open, onOpenChange, editing }: { open: boolean; onOpenChange: (open: boolean) => void; editing: ReorderRule | null }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { catalog, suppliers, sites } = useLookups();

  const [productId, setProductId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [reorderPoint, setReorderPoint] = useState("");
  const [orderUpTo, setOrderUpTo] = useState("");
  const [minOrder, setMinOrder] = useState("0");
  const [supplierId, setSupplierId] = useState("");

  useEffect(() => {
    if (!open) return;
    setProductId(editing?.product_id ?? "");
    setSiteId(editing?.site_id ?? "");
    setReorderPoint(editing ? String(editing.reorder_point) : "");
    setOrderUpTo(editing ? String(editing.order_up_to) : "");
    setMinOrder(editing ? String(editing.min_order_quantity) : "0");
    setSupplierId(editing?.preferred_supplier_id ?? "");
  }, [open, editing]);

  const mutation = useMutation({
    mutationFn: () => {
      const levels = {
        reorder_point: Number(reorderPoint),
        order_up_to: Number(orderUpTo),
        min_order_quantity: Number(minOrder || 0),
        preferred_supplier_id: supplierId || null,
      };
      return editing
        ? updateReorderRule(token, editing.id, levels)
        : createReorderRule(token, { ...levels, product_id: productId, site_id: siteId || null });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REORDER_RULES_QUERY_KEY });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t("warehouse.replenishment.rules.dialog.editTitle") : t("warehouse.replenishment.rules.dialog.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.replenishment.rules.dialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>{t("warehouse.replenishment.column.product")}</Label>
            <ProductSelect products={catalog} value={productId} onChange={(e) => setProductId(e.target.value)} disabled={editing !== null} />
          </div>
          <div className="space-y-1">
            <Label>{t("warehouse.replenishment.column.scope")}</Label>
            <Select value={siteId} onChange={(e) => setSiteId(e.target.value)} disabled={editing !== null}>
              <option value="">{t("warehouse.replenishment.scope.allSites")}</option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>{t("warehouse.replenishment.column.reorderPoint")}</Label>
              <Input type="number" min={0} step="any" value={reorderPoint} onChange={(e) => setReorderPoint(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t("warehouse.replenishment.column.orderUpTo")}</Label>
              <Input type="number" min={0} step="any" value={orderUpTo} onChange={(e) => setOrderUpTo(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t("warehouse.replenishment.column.minOrder")}</Label>
              <Input type="number" min={0} step="any" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1">
            <Label>{t("warehouse.replenishment.column.supplier")}</Label>
            <Select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">—</option>
              {suppliers.map((supplier) => (
                <option key={supplier.id} value={supplier.id}>
                  {supplier.name}
                </option>
              ))}
            </Select>
          </div>
          {mutation.isError && <p className="text-sm text-destructive">{errorText(mutation.error, t("warehouse.replenishment.dialog.error"))}</p>}
          <div className="flex justify-end">
            <Button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || reorderPoint === "" || orderUpTo === "" || (!editing && productId === "")}
            >
              {t("common.save")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ApproveDialog({ proposal, onClose }: { proposal: ReplenishmentProposal | null; onClose: () => void }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { suppliers, productName } = useLookups();
  const [quantity, setQuantity] = useState("");
  const [supplierId, setSupplierId] = useState("");

  useEffect(() => {
    setQuantity(proposal ? String(proposal.quantity) : "");
    setSupplierId(proposal?.supplier_id ?? "");
  }, [proposal]);

  const mutation = useMutation({
    mutationFn: () => approveProposal(token, proposal!.id, { quantity: Number(quantity), supplier_id: supplierId || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROPOSALS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["procurement", "purchase-orders"] });
      toast.success(t("warehouse.replenishment.approve.sent"));
      onClose();
    },
  });

  return (
    <Dialog open={proposal !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("warehouse.replenishment.approve.title")}</DialogTitle>
          <DialogDescription>
            {proposal ? productName(proposal.product_id) : ""} · {t("warehouse.replenishment.approve.description")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>{t("warehouse.replenishment.column.quantity")}</Label>
            <Input type="number" min={0} step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>{t("warehouse.replenishment.column.supplier")}</Label>
            <Select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">—</option>
              {suppliers.map((supplier) => (
                <option key={supplier.id} value={supplier.id}>
                  {supplier.name}
                </option>
              ))}
            </Select>
          </div>
          {mutation.isError && <p className="text-sm text-destructive">{errorText(mutation.error, t("warehouse.replenishment.dialog.error"))}</p>}
          <div className="flex justify-end">
            <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || quantity === "" || Number(quantity) <= 0}>
              {t("warehouse.replenishment.action.approve")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const PROPOSAL_VARIANT: Record<ProposalStatus, BadgeProps["variant"]> = {
  open: "warning",
  approved: "primary",
  fulfilled: "success",
  dismissed: "outline",
};
const PROPOSAL_FILTERS = ["open", "approved", "fulfilled", "dismissed", "all"] as const;
type ProposalFilter = (typeof PROPOSAL_FILTERS)[number];

function ProposalsCard() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { productName, supplierName, siteName } = useLookups();
  const { data: proposals = [] } = useQuery({ queryKey: PROPOSALS_QUERY_KEY, queryFn: () => listProposals(token) });
  const [filter, setFilter] = useState<ProposalFilter>("open");
  const [approving, setApproving] = useState<ReplenishmentProposal | null>(null);
  const canManage = hasPermission("warehouse.manage_replenishment");

  const evaluateMutation = useMutation({
    mutationFn: () => evaluateReplenishment(token),
    onSuccess: (outcome) => {
      queryClient.invalidateQueries({ queryKey: PROPOSALS_QUERY_KEY });
      toast.success(`${t("warehouse.replenishment.evaluate.done")}: ${outcome.created.length}`);
    },
  });
  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissProposal(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROPOSALS_QUERY_KEY }),
  });

  const columnFilters = useColumnFilters<ReplenishmentProposal>([
    { key: "product", kind: "text", getValue: (row) => productName(row.product_id) },
    { key: "available", kind: "range", getValue: (row) => row.available_at_proposal },
    { key: "quantity", kind: "range", getValue: (row) => row.quantity },
    { key: "supplier", kind: "text", getValue: (row) => supplierName(row.supplier_id) },
  ]);
  const columns: ColumnDef<ReplenishmentProposal>[] = [
    {
      key: "product",
      header: t("warehouse.replenishment.column.product"),
      cell: (row) => (
        <span>
          {productName(row.product_id)}
          {row.site_id && <span className="text-muted-foreground"> · {siteName(row.site_id)}</span>}
        </span>
      ),
      filterCell: columnFilters.textCell("product", t("warehouse.replenishment.column.product")),
    },
    { key: "available", header: t("warehouse.replenishment.column.available"), cell: (row) => row.available_at_proposal, filterCell: columnFilters.rangeCell("available") },
    { key: "quantity", header: t("warehouse.replenishment.column.quantity"), cell: (row) => row.quantity, filterCell: columnFilters.rangeCell("quantity") },
    {
      key: "supplier",
      header: t("warehouse.replenishment.column.supplier"),
      cell: (row) => supplierName(row.supplier_id),
      filterCell: columnFilters.textCell("supplier", t("warehouse.replenishment.column.supplier")),
    },
    {
      key: "status",
      header: t("warehouse.replenishment.column.status"),
      cell: (row) => <Badge variant={PROPOSAL_VARIANT[row.status]}>{t(`warehouse.replenishment.status.${row.status}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "created",
      header: t("warehouse.replenishment.column.created"),
      cell: (row) => new Date(row.created_at).toLocaleDateString(),
      filterCell: { type: "blank" },
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) =>
        row.status === "open" && canManage ? (
          <div className="flex justify-end gap-1">
            <Button variant="ghost" size="sm" onClick={() => setApproving(row)}>
              <Check className="h-3.5 w-3.5" />
              {t("warehouse.replenishment.action.approve")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => dismissMutation.mutate(row.id)} disabled={dismissMutation.isPending}>
              <X className="h-3.5 w-3.5" />
              {t("warehouse.replenishment.action.dismiss")}
            </Button>
          </div>
        ) : null,
      filterCell: { type: "blank" },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.replenishmentProposals",
    columns,
  );
  const rows = columnFilters.apply(filter === "all" ? proposals : proposals.filter((p) => p.status === filter));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.replenishment.proposals.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <FilterTabs
            value={filter}
            onChange={setFilter}
            options={PROPOSAL_FILTERS.map((s) => ({ value: s, label: s === "all" ? t("common.all") : t(`warehouse.replenishment.status.${s}`) }))}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          <div className="flex-1" />
          {canManage && (
            <Button size="sm" variant="outline" onClick={() => evaluateMutation.mutate()} disabled={evaluateMutation.isPending}>
              <RefreshCw className="h-3.5 w-3.5" />
              {t("warehouse.replenishment.action.evaluate")}
            </Button>
          )}
        </div>
        {rows.length === 0 ? (
          <EmptyState icon={<RefreshCw className="h-5 w-5" />} title={t("warehouse.replenishment.proposals.empty")} description={t("warehouse.replenishment.proposals.emptyDescription")} />
        ) : (
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead key={column.key} width={getWidth(column.key)} onResize={(width) => setWidth(column.key, width)}>
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key}>{column.cell(row)}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <ApproveDialog proposal={approving} onClose={() => setApproving(null)} />
    </Card>
  );
}

const RULE_FILTERS = ["all", "active", "inactive"] as const;
type RuleFilter = (typeof RULE_FILTERS)[number];

function RulesCard() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { productName, supplierName, siteName } = useLookups();
  const { data: rules = [] } = useQuery({ queryKey: REORDER_RULES_QUERY_KEY, queryFn: () => listReorderRules(token) });
  const [filter, setFilter] = useState<RuleFilter>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ReorderRule | null>(null);
  const canManage = hasPermission("warehouse.manage_replenishment");
  const canEdit = hasPermission("warehouse.admin_reorder_rules");

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteReorderRule(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: REORDER_RULES_QUERY_KEY }),
    onError: (error) => toast.error(errorText(error, t("warehouse.replenishment.dialog.error"))),
  });
  const toggleMutation = useMutation({
    mutationFn: (rule: ReorderRule) => updateReorderRule(token, rule.id, { is_active: !rule.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: REORDER_RULES_QUERY_KEY }),
  });

  const columnFilters = useColumnFilters<ReorderRule>([
    { key: "product", kind: "text", getValue: (row) => productName(row.product_id) },
    { key: "scope", kind: "text", getValue: (row) => siteName(row.site_id) ?? t("warehouse.replenishment.scope.allSites") },
    { key: "reorderPoint", kind: "range", getValue: (row) => row.reorder_point },
    { key: "orderUpTo", kind: "range", getValue: (row) => row.order_up_to },
    { key: "supplier", kind: "text", getValue: (row) => supplierName(row.preferred_supplier_id) },
  ]);
  const columns: ColumnDef<ReorderRule>[] = [
    { key: "product", header: t("warehouse.replenishment.column.product"), cell: (row) => productName(row.product_id), filterCell: columnFilters.textCell("product", t("warehouse.replenishment.column.product")) },
    {
      key: "scope",
      header: t("warehouse.replenishment.column.scope"),
      cell: (row) => siteName(row.site_id) ?? t("warehouse.replenishment.scope.allSites"),
      filterCell: columnFilters.textCell("scope", t("warehouse.replenishment.column.scope")),
    },
    { key: "reorderPoint", header: t("warehouse.replenishment.column.reorderPoint"), cell: (row) => row.reorder_point, filterCell: columnFilters.rangeCell("reorderPoint") },
    { key: "orderUpTo", header: t("warehouse.replenishment.column.orderUpTo"), cell: (row) => row.order_up_to, filterCell: columnFilters.rangeCell("orderUpTo") },
    {
      key: "supplier",
      header: t("warehouse.replenishment.column.supplier"),
      cell: (row) => supplierName(row.preferred_supplier_id),
      filterCell: columnFilters.textCell("supplier", t("warehouse.replenishment.column.supplier")),
    },
    {
      key: "active",
      header: t("warehouse.replenishment.column.active"),
      cell: (row) => (
        <Badge variant={row.is_active ? "success" : "outline"}>
          {row.is_active ? t("warehouse.replenishment.rule.active") : t("warehouse.replenishment.rule.inactive")}
        </Badge>
      ),
      filterCell: { type: "blank" },
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) => (
        <div className="flex justify-end gap-1">
          {canEdit && (
            <>
              <Button
                variant="ghost"
                size="sm"
                aria-label={t("common.edit")}
                onClick={() => {
                  setEditing(row);
                  setDialogOpen(true);
                }}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => toggleMutation.mutate(row)}
                disabled={toggleMutation.isPending}
              >
                {row.is_active ? t("warehouse.replenishment.action.deactivate") : t("warehouse.replenishment.action.activate")}
              </Button>
            </>
          )}
          {canManage && (
            <Button variant="ghost" size="sm" aria-label={t("common.delete")} onClick={() => deleteMutation.mutate(row.id)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      ),
      filterCell: { type: "blank" },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.reorderRules",
    columns,
  );
  const byStatus = filter === "all" ? rules : rules.filter((r) => (filter === "active" ? r.is_active : !r.is_active));
  const rows = columnFilters.apply(byStatus);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.replenishment.rules.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <FilterTabs
            value={filter}
            onChange={setFilter}
            options={RULE_FILTERS.map((s) => ({
              value: s,
              label: s === "all" ? t("common.all") : t(s === "active" ? "warehouse.replenishment.rule.active" : "warehouse.replenishment.rule.inactive"),
            }))}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          <div className="flex-1" />
          {canManage && (
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              {t("warehouse.replenishment.rules.new")}
            </Button>
          )}
        </div>
        {rows.length === 0 ? (
          <EmptyState icon={<Plus className="h-5 w-5" />} title={t("warehouse.replenishment.rules.empty")} description={t("warehouse.replenishment.rules.emptyDescription")} />
        ) : (
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead key={column.key} width={getWidth(column.key)} onResize={(width) => setWidth(column.key, width)}>
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key}>{column.cell(row)}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <RuleDialog open={dialogOpen} onOpenChange={setDialogOpen} editing={editing} />
    </Card>
  );
}

export function ReplenishmentTab() {
  const { t } = useI18n();
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">{t("warehouse.replenishment.description")}</p>
      <ProposalsCard />
      <RulesCard />
    </div>
  );
}
