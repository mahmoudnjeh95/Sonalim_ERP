import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Recycle } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { formatQuantity } from "../../../lib/units";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { listProducts } from "../../warehouse/api";
import { isGrinderLine, listRegrindDefaults, listWorkCenters } from "../api";
import { T, useLabel } from "./shiftText";

export const REGRIND_DEFAULTS_QUERY_KEY = ["production", "regrind-defaults"] as const;

export interface RegrindChoice {
  /** Set only when the tenant has no default yet: saved as the default before approving. */
  defaultProductId: string | null;
  workCenterId: string | null;
}

/**
 * Shown before approving a shift that declares rebroyat: validation opens an OFR for it,
 * which needs the tenant's one rebroyat product and a line to run on. Missing either used
 * to fail the approval with REGRIND_DEFAULT_MISSING / MISSING_WORK_CENTER; here the
 * validator fills them in and approves in one go.
 */
export function RegrindConfirmDialog({
  regrindKg,
  lineRequired,
  busy,
  onConfirm,
  onClose,
}: {
  regrindKg: number;
  /** The server said the production order has no line, so "its own line" is not an option. */
  lineRequired: boolean;
  busy: boolean;
  onConfirm: (choice: RegrindChoice) => void;
  onClose: () => void;
}) {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const canSetDefault = hasPermission("production.manage_regrind");

  const defaults = useQuery({ queryKey: REGRIND_DEFAULTS_QUERY_KEY, queryFn: () => listRegrindDefaults(token) });
  const products = useQuery({ queryKey: ["production", "shift", "products"], queryFn: () => listProducts(token) });
  const workCenters = useQuery({ queryKey: ["production", "work-centers", "all"], queryFn: () => listWorkCenters(token) });

  const current = defaults.data?.find((row) => row.input_product_id === null)?.output_product_id ?? null;
  const productName = (id: string) => products.data?.find((p) => p.id === id)?.name ?? "—";
  const grinders = (workCenters.data ?? []).filter((w) => isGrinderLine(w) && !w.is_blocked);

  const [productId, setProductId] = useState("");
  const [workCenterId, setWorkCenterId] = useState("");
  // A grinder line is where an OFR belongs: pre-pick it when the plant has exactly one.
  useEffect(() => {
    if (!workCenterId && grinders.length === 1) setWorkCenterId(grinders[0].id);
  }, [grinders.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const loading = defaults.isLoading || products.isLoading || workCenters.isLoading;
  const productMissing = !loading && current === null;
  const ready =
    !loading && (!productMissing || (canSetDefault && !!productId)) && (!lineRequired || !!workCenterId);

  return (
    <Dialog open onOpenChange={(next) => !next && !busy && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Recycle className="h-4 w-4 text-primary" />
            {label(T.regrindTitle)}
          </DialogTitle>
          <DialogDescription>{label(T.regrindHint(formatQuantity(regrindKg, "kg")))}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="regrind_product">{label(T.regrindProduct)}</Label>
            {current !== null ? (
              <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-sm font-medium">{productName(current)}</p>
            ) : productMissing && canSetDefault ? (
              <>
                <Select
                  id="regrind_product"
                  value={productId}
                  onChange={(event) => setProductId(event.target.value)}
                  className="border-warning ring-2 ring-warning/30"
                >
                  <option value="">—</option>
                  {(products.data ?? []).map((product) => (
                    <option key={product.id} value={product.id}>
                      {product.name}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">{label(T.regrindProductMissing)}</p>
              </>
            ) : productMissing ? (
              <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">
                {label(T.regrindProductNoRight)}
              </p>
            ) : null}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="regrind_line">{label(T.regrindLine)}</Label>
            <Select
              id="regrind_line"
              value={workCenterId}
              onChange={(event) => setWorkCenterId(event.target.value)}
              className={lineRequired && !workCenterId ? "border-warning ring-2 ring-warning/30" : undefined}
            >
              <option value="">{lineRequired ? "—" : label(T.regrindLineFallback)}</option>
              {grinders.map((line) => (
                <option key={line.id} value={line.id}>
                  {line.name}
                </option>
              ))}
            </Select>
            {lineRequired && <p className="text-xs text-muted-foreground">{label(T.regrindLineRequired)}</p>}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {label(T.cancel)}
          </Button>
          <Button
            disabled={!ready || busy}
            onClick={() =>
              onConfirm({ defaultProductId: productMissing ? productId : null, workCenterId: workCenterId || null })
            }
          >
            {busy ? label(T.approving) : label(T.regrindConfirm)}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
