import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ClipboardList, Lock, Plus, Printer } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { ProductSelect } from "../../components/patterns/ProductSelect";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { useProductCatalog } from "../products/catalog";
import { listLocations } from "./api";
import {
  addInventoryLine,
  cancelInventory,
  closeInventory,
  getInventory,
  listInventories,
  openInventory,
  recordCount,
  type InventoryLine,
} from "./stockDocumentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];

export function InventoryTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("warehouse.manage_inventory");
  const canClose = hasPermission("warehouse.close_inventory");
  const { catalog } = useProductCatalog();
  const [openDialog, setOpenDialog] = useState(false);
  const [location, setLocation] = useState("");
  const [kind, setKind] = useState<"full" | "interim">("full");
  const [selected, setSelected] = useState<string | null>(null);
  const [extraProduct, setExtraProduct] = useState("");

  const { data: inventories = [] } = useQuery({ queryKey: ["warehouse", "inventories"], queryFn: () => listInventories(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: detail } = useQuery({
    queryKey: ["warehouse", "inventory", selected],
    queryFn: () => getInventory(token, selected!),
    enabled: selected !== null,
  });
  const locationName = (id: string) => locations.find((l) => l.id === id)?.name ?? "—";

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["warehouse"] });
  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const openMutation = useMutation({
    mutationFn: () => openInventory(token, { location_id: location, type: kind }),
    onSuccess: (inventory) => {
      refresh();
      setOpenDialog(false);
      setSelected(inventory.id);
      toast.success(t("inventory.opened"));
    },
    onError: fail("inventory.openError"),
  });
  const countMutation = useMutation({
    mutationFn: (args: { line: InventoryLine; which: 1 | 2 | 3; quantity: number | null; observation?: string }) =>
      recordCount(token, selected!, args.line.id, { which: args.which, quantity: args.quantity, observation: args.observation }),
    onSuccess: refresh,
    onError: fail("inventory.countError"),
  });
  const addLineMutation = useMutation({
    mutationFn: () => addInventoryLine(token, selected!, extraProduct),
    onSuccess: () => {
      refresh();
      setExtraProduct("");
    },
    onError: fail("inventory.countError"),
  });
  const closeMutation = useMutation({
    mutationFn: () => closeInventory(token, selected!),
    onSuccess: () => {
      refresh();
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      toast.success(t("inventory.closed"));
    },
    onError: fail("inventory.closeError"),
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelInventory(token, selected!),
    onSuccess: () => {
      refresh();
      toast.success(t("inventory.cancelled"));
    },
    onError: fail("inventory.closeError"),
  });

  if (selected && detail) {
    const editable = detail.status === "open" && canManage;
    const counted = (value: string | null) => (value === null ? "" : String(Number(value)));
    return (
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <CardTitle>
              {detail.number} · {locationName(detail.location_id)}
            </CardTitle>
            <StatusBadge status={detail.status === "open" ? "ongoing" : detail.status === "closed" ? "closed" : "cancelled"} />
            {detail.type === "full" && detail.status === "open" && (
              <span className="inline-flex items-center gap-1 text-xs text-warning">
                <Lock className="h-3.5 w-3.5" />
                {t("inventory.frozen")}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer className="h-3.5 w-3.5" />
              {t("inventory.print")}
            </Button>
            {detail.status === "open" && canClose && (
              <Button size="sm" disabled={closeMutation.isPending} onClick={() => closeMutation.mutate()}>
                {t("inventory.close")}
              </Button>
            )}
            {detail.status === "open" && canManage && (
              <Button size="sm" variant="outline" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
                {t("inventory.cancel")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4 p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("inventory.column.product")}</TableHead>
                <TableHead className="text-right">{t("inventory.column.theoretical")}</TableHead>
                <TableHead className="w-24">{t("inventory.column.count1")}</TableHead>
                <TableHead className="w-24">{t("inventory.column.count2")}</TableHead>
                <TableHead className="w-24">{t("inventory.column.count3")}</TableHead>
                <TableHead className="text-right">{t("inventory.column.variance")}</TableHead>
                <TableHead>{t("inventory.column.observation")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(detail.lines ?? []).map((line) => {
                const needsThird = line.count_1 !== null && line.count_2 !== null && Number(line.count_1) !== Number(line.count_2);
                const variance = line.variance === null ? null : Number(line.variance);
                return (
                  <TableRow key={line.id}>
                    <TableCell>
                      <span className="font-medium">{line.name}</span>
                      <span className="block text-xs text-muted-foreground">{line.sku}</span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{Number(line.theoretical_qty)}</TableCell>
                    {([1, 2, 3] as const).map((which) => {
                      const field = (`count_${which}`) as "count_1" | "count_2" | "count_3";
                      return (
                        <TableCell key={which}>
                          <Input
                            type="number"
                            step="any"
                            min="0"
                            key={`${line.id}-${which}-${line[field]}`}
                            defaultValue={counted(line[field])}
                            disabled={!editable || (which === 3 && !needsThird)}
                            onBlur={(e) => {
                              const raw = e.target.value;
                              const next = raw === "" ? null : Number(raw);
                              if (next !== (line[field] === null ? null : Number(line[field]))) countMutation.mutate({ line, which, quantity: next });
                            }}
                          />
                        </TableCell>
                      );
                    })}
                    <TableCell className={`text-right tabular-nums ${variance ? "font-medium text-destructive" : ""}`}>{variance === null ? "—" : variance}</TableCell>
                    <TableCell>
                      <Input
                        key={`${line.id}-obs-${line.observation}`}
                        defaultValue={line.observation ?? ""}
                        placeholder={variance ? t("inventory.observationRequired") : ""}
                        disabled={!editable}
                        onBlur={(e) => {
                          if (e.target.value !== (line.observation ?? "") && line.count_1 !== null)
                            countMutation.mutate({ line, which: 1, quantity: Number(line.count_1), observation: e.target.value });
                        }}
                      />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {editable && (
            <div className="flex items-end gap-2 px-6 pb-4">
              <div className="flex-1 space-y-1.5">
                <Label>{t("inventory.addProduct")}</Label>
                <ProductSelect products={catalog} value={extraProduct} onChange={(e) => setExtraProduct(e.target.value)} />
              </div>
              <Button variant="outline" disabled={!extraProduct || addLineMutation.isPending} onClick={() => addLineMutation.mutate()}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("inventory.title")}</CardTitle>
          {canManage && (
            <Button onClick={() => setOpenDialog(true)}>
              <Plus className="h-4 w-4" />
              {t("inventory.new")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("voucher.column.number")}</TableHead>
                <TableHead>{t("inventory.column.location")}</TableHead>
                <TableHead>{t("voucher.column.type")}</TableHead>
                <TableHead>{t("voucher.column.status")}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {inventories.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="p-0">
                    <EmptyState icon={<ClipboardList className="h-5 w-5" />} title={t("inventory.empty.title")} description={t("inventory.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {inventories.map((inventory) => (
                <TableRow key={inventory.id}>
                  <TableCell className="font-mono text-xs">{inventory.number}</TableCell>
                  <TableCell>{locationName(inventory.location_id)}</TableCell>
                  <TableCell>{t(inventory.type === "full" ? "inventory.type.full" : "inventory.type.interim")}</TableCell>
                  <TableCell>
                    <StatusBadge status={inventory.status === "open" ? "ongoing" : inventory.status === "closed" ? "closed" : "cancelled"} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => setSelected(inventory.id)}>
                      {t("inventory.open")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={openDialog} onOpenChange={setOpenDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("inventory.new")}</DialogTitle>
            <DialogDescription>{t("inventory.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); openMutation.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="inv_loc">{t("inventory.column.location")}</Label>
              <Select id="inv_loc" required value={location} onChange={(e) => setLocation(e.target.value)}>
                <option value="">—</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="inv_kind">{t("voucher.column.type")}</Label>
              <Select id="inv_kind" value={kind} onChange={(e) => setKind(e.target.value as "full" | "interim")}>
                <option value="full">{t("inventory.type.full")}</option>
                <option value="interim">{t("inventory.type.interim")}</option>
              </Select>
              <p className="text-xs text-muted-foreground">{t(kind === "full" ? "inventory.type.fullHelp" : "inventory.type.interimHelp")}</p>
            </div>
            <Button type="submit" className="w-full" disabled={openMutation.isPending}>
              {t("inventory.start")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
