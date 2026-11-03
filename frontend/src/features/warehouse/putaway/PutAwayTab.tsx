import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { useProductCatalog } from "../../products/catalog";
import { listSites } from "../locations/api";
import { listLocations, listStock } from "../api";
import {
  confirmPutaway,
  createPutawayRule,
  deletePutawayRule,
  getPutawaySuggestions,
  listPutawayRules,
  suggestionsQueryKey,
  PUTAWAY_RULES_QUERY_KEY,
} from "./api";

function NewRuleDialog({
  open,
  onOpenChange,
  siteId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  siteId: string;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const bins = locations.filter((l) => l.site_id === siteId && l.location_type === "bin");

  const [productId, setProductId] = useState("");
  const [targetLocationId, setTargetLocationId] = useState("");

  useEffect(() => {
    if (open) {
      setProductId(products[0]?.id ?? "");
      setTargetLocationId(bins[0]?.id ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const mutation = useMutation({
    mutationFn: () => createPutawayRule(token, { site_id: siteId, product_id: productId, target_location_id: targetLocationId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PUTAWAY_RULES_QUERY_KEY });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("warehouse.putaway.rules.dialog.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.putaway.rules.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="rule-product">{t("warehouse.putaway.field.product")}</Label>
            <Select id="rule-product" value={productId} onChange={(event) => setProductId(event.target.value)}>
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-target">{t("warehouse.putaway.field.targetLocation")}</Label>
            <Select id="rule-target" value={targetLocationId} onChange={(event) => setTargetLocationId(event.target.value)}>
              {bins.map((bin) => (
                <option key={bin.id} value={bin.id}>
                  {bin.name} ({bin.code})
                </option>
              ))}
            </Select>
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.putaway.dialog.error")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending || !productId || !targetLocationId}>
            {t("warehouse.putaway.rules.dialog.submit")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PutAwayTab() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();
  const canManage = hasPermission("warehouse.manage_putaway");

  const { data: sites = [] } = useQuery({ queryKey: ["warehouse", "sites"], queryFn: () => listSites(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: stock = [] } = useQuery({ queryKey: ["warehouse", "stock"], queryFn: () => listStock(token) });
  const { data: rules = [] } = useQuery({ queryKey: PUTAWAY_RULES_QUERY_KEY, queryFn: () => listPutawayRules(token) });

  const [siteId, setSiteId] = useState("");
  const [productId, setProductId] = useState("");
  const [fromLocationId, setFromLocationId] = useState("");
  const [toLocationId, setToLocationId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [ruleDialogOpen, setRuleDialogOpen] = useState(false);

  useEffect(() => {
    if (!siteId && sites.length > 0) setSiteId(sites[0].id);
  }, [sites, siteId]);

  const siteLocationIds = new Set(locations.filter((l) => l.site_id === siteId).map((l) => l.id));
  const fromCandidates = stock.filter((item) => item.product_id === productId && siteLocationIds.has(item.location_id) && item.quantity_on_hand > 0);

  useEffect(() => {
    setFromLocationId(fromCandidates[0]?.location_id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId, siteId]);

  const { data: suggestions = [] } = useQuery({
    queryKey: siteId && productId && fromLocationId ? suggestionsQueryKey(siteId, productId, fromLocationId) : ["warehouse", "putawaySuggestions", "none"],
    queryFn: () => getPutawaySuggestions(token, siteId, productId, fromLocationId),
    enabled: siteId !== "" && productId !== "" && fromLocationId !== "",
  });

  useEffect(() => {
    setToLocationId(suggestions[0]?.id ?? "");
  }, [suggestions]);

  const locationName = (locationId: string) => locations.find((l) => l.id === locationId)?.name ?? locationId;
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;
  const ruleTargetFor = (product: string, site: string) => rules.find((r) => r.product_id === product && r.site_id === site)?.target_location_id;
  const reasonFor = (locationId: string) => {
    if (ruleTargetFor(productId, siteId) === locationId) return t("warehouse.putaway.reason.rule");
    if (stock.some((item) => item.location_id === locationId && item.product_id === productId && item.quantity_on_hand > 0)) {
      return t("warehouse.putaway.reason.sameProduct");
    }
    return t("warehouse.putaway.reason.empty");
  };

  const fromItem = fromCandidates.find((item) => item.location_id === fromLocationId);

  const confirmMutation = useMutation({
    mutationFn: () =>
      confirmPutaway(token, { site_id: siteId, product_id: productId, from_location_id: fromLocationId, to_location_id: toLocationId, quantity: Number(quantity) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: suggestionsQueryKey(siteId, productId, fromLocationId) });
      setQuantity("");
    },
  });

  const deleteRuleMutation = useMutation({
    mutationFn: (ruleId: string) => deletePutawayRule(token, ruleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PUTAWAY_RULES_QUERY_KEY }),
  });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("warehouse.putaway.suggest.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="pa-site">{t("warehouse.putaway.field.site")}</Label>
              <Select id="pa-site" value={siteId} onChange={(event) => setSiteId(event.target.value)}>
                {sites.map((site) => (
                  <option key={site.id} value={site.id}>
                    {site.name} ({site.code})
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pa-product">{t("warehouse.putaway.field.product")}</Label>
              <Select id="pa-product" value={productId} onChange={(event) => setProductId(event.target.value)}>
                <option value="">{t("warehouse.putaway.field.product.choose")}</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pa-from">{t("warehouse.putaway.field.fromLocation")}</Label>
              <Select id="pa-from" value={fromLocationId} onChange={(event) => setFromLocationId(event.target.value)} disabled={fromCandidates.length === 0}>
                {fromCandidates.map((item) => (
                  <option key={item.location_id} value={item.location_id}>
                    {locationName(item.location_id)} ({item.quantity_on_hand})
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {productId && fromLocationId && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">{t("warehouse.putaway.suggestions.title")}</p>
              {suggestions.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("warehouse.putaway.suggestions.empty")}</p>
              ) : (
                <div className="space-y-1.5">
                  {suggestions.map((location) => (
                    <label
                      key={location.id}
                      className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm hover:border-primary/40"
                    >
                      <span className="flex items-center gap-2">
                        <input type="radio" name="pa-target" checked={toLocationId === location.id} onChange={() => setToLocationId(location.id)} />
                        {location.name} ({location.code})
                      </span>
                      <Badge variant="outline">{reasonFor(location.id)}</Badge>
                    </label>
                  ))}
                </div>
              )}

              <div className="flex items-end gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="pa-quantity">{t("warehouse.putaway.field.quantity")}</Label>
                  <Input
                    id="pa-quantity"
                    type="number"
                    step="any"
                    max={fromItem?.quantity_on_hand}
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                    className="w-32"
                  />
                </div>
                <Button
                  onClick={() => confirmMutation.mutate()}
                  disabled={!toLocationId || !quantity || confirmMutation.isPending}
                >
                  {t("warehouse.putaway.action.confirm")}
                </Button>
              </div>
              {confirmMutation.isError && (
                <p className="text-sm text-destructive">
                  {confirmMutation.error instanceof ApiError ? confirmMutation.error.message : t("warehouse.putaway.dialog.error")}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("warehouse.putaway.rules.title")}</CardTitle>
          {canManage && (
            <Button size="sm" onClick={() => setRuleDialogOpen(true)}>
              {t("warehouse.putaway.rules.newRule")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {rules.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">{t("warehouse.putaway.rules.empty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("warehouse.putaway.field.product")}</TableHead>
                  <TableHead>{t("warehouse.putaway.field.targetLocation")}</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell>{productName(rule.product_id)}</TableCell>
                    <TableCell>{locationName(rule.target_location_id)}</TableCell>
                    <TableCell>
                      {canManage && (
                        <Button variant="ghost" size="sm" onClick={() => deleteRuleMutation.mutate(rule.id)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <NewRuleDialog open={ruleDialogOpen} onOpenChange={setRuleDialogOpen} siteId={siteId} />
    </div>
  );
}
