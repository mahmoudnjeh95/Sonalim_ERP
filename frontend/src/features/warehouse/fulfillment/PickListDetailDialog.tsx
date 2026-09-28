import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Badge } from "../../../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { useProductCatalog } from "../../products/catalog";
import {
  cancelPickList,
  completePicking,
  getPickList,
  packPickList,
  pickListQueryKey,
  shipShipment,
  submitPick,
  updateShipment,
  PICK_LISTS_QUERY_KEY,
  SHIPMENTS_QUERY_KEY,
  type PickListLine,
  type Shipment,
} from "./api";

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function PickLineRow({
  line,
  productName,
  pickable,
  pickListId,
}: {
  line: PickListLine;
  productName: string;
  pickable: boolean;
  pickListId: string;
}) {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(line.quantity_picked !== null ? String(line.quantity_picked) : String(line.quantity_requested));

  const mutation = useMutation({
    mutationFn: () => submitPick(token, pickListId, line.id, Number(draft)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pickListQueryKey(pickListId) });
      queryClient.invalidateQueries({ queryKey: PICK_LISTS_QUERY_KEY });
    },
  });
  const short = line.quantity_picked !== null && line.quantity_picked < line.quantity_requested;

  return (
    <TableRow>
      <TableCell>{productName}</TableCell>
      <TableCell>{line.quantity_requested}</TableCell>
      <TableCell>
        {pickable && hasPermission("warehouse.manage_fulfillment") ? (
          <div className="flex items-center gap-1.5">
            <Input type="number" step="any" min={0} value={draft} onChange={(e) => setDraft(e.target.value)} className="h-8 w-24" />
            <Button size="sm" variant="outline" onClick={() => mutation.mutate()} disabled={draft === "" || mutation.isPending}>
              {t("warehouse.fulfillment.line.record")}
            </Button>
          </div>
        ) : (
          (line.quantity_picked ?? "—")
        )}
        {mutation.isError && <p className="mt-1 text-xs text-destructive">{errorText(mutation.error, t("warehouse.fulfillment.dialog.error"))}</p>}
      </TableCell>
      <TableCell>
        {line.quantity_picked === null ? (
          <Badge variant="default">{t("warehouse.fulfillment.line.pending")}</Badge>
        ) : short ? (
          <Badge variant="warning">{t("warehouse.fulfillment.line.short")}</Badge>
        ) : (
          <Badge variant="success">{t("warehouse.fulfillment.line.picked")}</Badge>
        )}
      </TableCell>
    </TableRow>
  );
}

function PackForm({ pickListId, shipment, onDone }: { pickListId: string; shipment: Shipment | null; onDone: () => void }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [packageCount, setPackageCount] = useState("1");
  const [weight, setWeight] = useState("");
  const [carrier, setCarrier] = useState("");
  const [tracking, setTracking] = useState("");

  useEffect(() => {
    setPackageCount(shipment ? String(shipment.package_count) : "1");
    setWeight(shipment?.total_weight_kg != null ? String(shipment.total_weight_kg) : "");
    setCarrier(shipment?.carrier ?? "");
    setTracking(shipment?.tracking_reference ?? "");
  }, [shipment]);

  const input = {
    package_count: Number(packageCount),
    total_weight_kg: weight === "" ? null : Number(weight),
    carrier: carrier || null,
    tracking_reference: tracking || null,
  };
  const mutation = useMutation({
    mutationFn: () => (shipment ? updateShipment(token, shipment.id, input) : packPickList(token, pickListId, input)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: pickListQueryKey(pickListId) });
      queryClient.invalidateQueries({ queryKey: SHIPMENTS_QUERY_KEY });
      onDone();
    },
  });

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="space-y-1">
          <Label>{t("warehouse.fulfillment.field.packageCount")}</Label>
          <Input type="number" min={1} step={1} value={packageCount} onChange={(e) => setPackageCount(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>{t("warehouse.fulfillment.field.weight")}</Label>
          <Input type="number" min={0} step="any" value={weight} onChange={(e) => setWeight(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>{t("warehouse.fulfillment.field.carrier")}</Label>
          <Input value={carrier} onChange={(e) => setCarrier(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>{t("warehouse.fulfillment.field.tracking")}</Label>
          <Input value={tracking} onChange={(e) => setTracking(e.target.value)} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => mutation.mutate()} disabled={packageCount === "" || mutation.isPending}>
          {shipment ? t("common.save") : t("warehouse.fulfillment.action.pack")}
        </Button>
        {mutation.isError && <p className="text-sm text-destructive">{errorText(mutation.error, t("warehouse.fulfillment.dialog.error"))}</p>}
      </div>
    </div>
  );
}

export function PickListDetailDialog({
  open,
  onOpenChange,
  pickListId,
  customerName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pickListId: string | null;
  customerName: (partnerId: string | null) => string;
}) {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();
  const [editingShipment, setEditingShipment] = useState(false);

  const { data: detail } = useQuery({
    queryKey: pickListId ? pickListQueryKey(pickListId) : ["warehouse", "pickLists", "none"],
    queryFn: () => getPickList(token, pickListId!),
    enabled: open && pickListId !== null,
  });

  useEffect(() => {
    if (!open) setEditingShipment(false);
  }, [open]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: PICK_LISTS_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: SHIPMENTS_QUERY_KEY });
    if (pickListId) queryClient.invalidateQueries({ queryKey: pickListQueryKey(pickListId) });
  };
  const stockAffecting = () => {
    invalidate();
    queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
    queryClient.invalidateQueries({ queryKey: ["sales", "orders"] });
  };
  const completeMutation = useMutation({ mutationFn: () => completePicking(token, pickListId!), onSuccess: invalidate });
  const cancelMutation = useMutation({ mutationFn: () => cancelPickList(token, pickListId!), onSuccess: stockAffecting });
  const shipMutation = useMutation({
    mutationFn: () => shipShipment(token, detail!.shipment!.id),
    onSuccess: stockAffecting,
  });

  const canManage = hasPermission("warehouse.manage_fulfillment");
  const canAdminShipment = hasPermission("warehouse.admin_shipments");
  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;
  const actionError = [completeMutation, cancelMutation, shipMutation].find((m) => m.isError)?.error;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t("warehouse.fulfillment.detail.title")} {detail?.number}
          </DialogTitle>
          {detail && (
            <DialogDescription>
              {t(`warehouse.fulfillment.status.${detail.status}`)} · {customerName(detail.partner_id)}
            </DialogDescription>
          )}
        </DialogHeader>

        {detail && (
          <>
            {canManage && (
              <div className="flex flex-wrap items-center gap-2">
                {(detail.status === "open" || detail.status === "picking") && (
                  <Button size="sm" onClick={() => completeMutation.mutate()} disabled={completeMutation.isPending}>
                    {t("warehouse.fulfillment.action.completePicking")}
                  </Button>
                )}
                {detail.shipment?.status === "packed" && (
                  <Button size="sm" onClick={() => shipMutation.mutate()} disabled={shipMutation.isPending}>
                    {t("warehouse.fulfillment.action.ship")}
                  </Button>
                )}
                {["open", "picking", "picked"].includes(detail.status) && !detail.shipment && (
                  <Button variant="outline" size="sm" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>
                    {t("warehouse.fulfillment.action.cancel")}
                  </Button>
                )}
              </div>
            )}
            {actionError != null && <p className="text-sm text-destructive">{errorText(actionError, t("warehouse.fulfillment.dialog.error"))}</p>}

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("warehouse.fulfillment.column.product")}</TableHead>
                  <TableHead>{t("warehouse.fulfillment.column.requested")}</TableHead>
                  <TableHead>{t("warehouse.fulfillment.column.picked")}</TableHead>
                  <TableHead>{t("warehouse.fulfillment.column.lineStatus")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.lines.map((line) => (
                  <PickLineRow
                    key={line.id}
                    line={line}
                    productName={productName(line.product_id)}
                    pickable={detail.status === "open" || detail.status === "picking"}
                    pickListId={detail.id}
                  />
                ))}
              </TableBody>
            </Table>

            {detail.status === "picked" && !detail.shipment && canManage && (
              <div className="space-y-2">
                <h3 className="text-sm font-medium">{t("warehouse.fulfillment.pack.title")}</h3>
                <PackForm pickListId={detail.id} shipment={null} onDone={() => undefined} />
              </div>
            )}

            {detail.shipment && (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium">
                    {t("warehouse.fulfillment.shipment.title")} {detail.shipment.number}
                  </h3>
                  <Badge variant={detail.shipment.status === "shipped" ? "success" : "primary"}>
                    {t(`warehouse.fulfillment.shipmentStatus.${detail.shipment.status}`)}
                  </Badge>
                  <div className="flex-1" />
                  {canAdminShipment && !editingShipment && (
                    <Button variant="ghost" size="sm" onClick={() => setEditingShipment(true)}>
                      {t("common.edit")}
                    </Button>
                  )}
                </div>
                {editingShipment ? (
                  <PackForm pickListId={detail.id} shipment={detail.shipment} onDone={() => setEditingShipment(false)} />
                ) : (
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
                    <dt className="text-muted-foreground">{t("warehouse.fulfillment.field.packageCount")}</dt>
                    <dd>{detail.shipment.package_count}</dd>
                    <dt className="text-muted-foreground">{t("warehouse.fulfillment.field.weight")}</dt>
                    <dd>{detail.shipment.total_weight_kg ?? "—"}</dd>
                    <dt className="text-muted-foreground">{t("warehouse.fulfillment.field.carrier")}</dt>
                    <dd>{detail.shipment.carrier ?? "—"}</dd>
                    <dt className="text-muted-foreground">{t("warehouse.fulfillment.field.tracking")}</dt>
                    <dd>{detail.shipment.tracking_reference ?? "—"}</dd>
                  </dl>
                )}
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
