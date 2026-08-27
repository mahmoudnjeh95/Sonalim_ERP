import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Tags } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listProducts } from "../warehouse/api";
import {
  createProductAttribute,
  createProductAttributeValue,
  createProductVariant,
  listProductAttributeValues,
  listProductAttributes,
} from "./api";

const ATTRIBUTES_QUERY_KEY = ["core", "product-attributes"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;

export function VariantAttributesTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: attributes = [] } = useQuery({ queryKey: ATTRIBUTES_QUERY_KEY, queryFn: () => listProductAttributes(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const [selectedAttributeId, setSelectedAttributeId] = useState<string | null>(null);

  const { data: values = [] } = useQuery({
    queryKey: ["core", "product-attributes", selectedAttributeId, "values"],
    queryFn: () => listProductAttributeValues(token, selectedAttributeId!),
    enabled: selectedAttributeId !== null,
  });

  const [newAttributeName, setNewAttributeName] = useState("");
  const createAttributeMutation = useMutation({
    mutationFn: (name: string) => createProductAttribute(token, name),
    onSuccess: (attribute) => {
      queryClient.invalidateQueries({ queryKey: ATTRIBUTES_QUERY_KEY });
      setNewAttributeName("");
      setSelectedAttributeId(attribute.id);
    },
    onError: (error) => {
      toast.error(t("products.variantAttributes.attributeError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const [newValue, setNewValue] = useState("");
  const createValueMutation = useMutation({
    mutationFn: ({ attributeId, value }: { attributeId: string; value: string }) => createProductAttributeValue(token, attributeId, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["core", "product-attributes", selectedAttributeId, "values"] });
      setNewValue("");
    },
    onError: (error) => {
      toast.error(t("products.variantAttributes.valueError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const parentEligibleProducts = products.filter((p) => !p.parent_product_id);
  const [variantParentId, setVariantParentId] = useState("");
  const [variantSku, setVariantSku] = useState("");
  const [variantName, setVariantName] = useState("");
  const [variantValueIds, setVariantValueIds] = useState<string[]>([]);

  const createVariantMutation = useMutation({
    mutationFn: () =>
      createProductVariant(token, variantParentId, { sku: variantSku, name: variantName, attribute_value_ids: variantValueIds }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      setVariantSku("");
      setVariantName("");
      setVariantValueIds([]);
      toast.success(t("products.variantAttributes.variantCreated"));
    },
    onError: (error) => {
      toast.error(t("products.variantAttributes.variantError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{t("products.variantAttributes.title")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("products.variantAttributes.subtitle")}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-1.5">
            <Input
              value={newAttributeName}
              onChange={(e) => setNewAttributeName(e.target.value)}
              placeholder={t("products.variantAttributes.newAttribute")}
            />
            <Button
              variant="outline"
              onClick={() => newAttributeName.trim() && createAttributeMutation.mutate(newAttributeName.trim())}
              disabled={createAttributeMutation.isPending}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>

          {attributes.length === 0 ? (
            <EmptyState icon={<Tags className="h-5 w-5" />} title={t("products.variantAttributes.empty.title")} description={t("products.variantAttributes.empty.description")} />
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {attributes.map((attribute) => (
                <button key={attribute.id} type="button" onClick={() => setSelectedAttributeId(attribute.id)}>
                  <Badge variant={selectedAttributeId === attribute.id ? "primary" : "outline"}>{attribute.name}</Badge>
                </button>
              ))}
            </div>
          )}

          {selectedAttributeId && (
            <div className="space-y-2 rounded-lg border border-border p-3">
              <Label className="text-xs text-muted-foreground">{t("products.variantAttributes.values")}</Label>
              <div className="flex flex-wrap gap-1.5">
                {values.map((value) => (
                  <Badge key={value.id} variant="default">
                    {value.value}
                  </Badge>
                ))}
              </div>
              <div className="flex gap-1.5">
                <Input value={newValue} onChange={(e) => setNewValue(e.target.value)} placeholder={t("products.variantAttributes.newValue")} className="h-8 text-xs" />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => newValue.trim() && createValueMutation.mutate({ attributeId: selectedAttributeId, value: newValue.trim() })}
                  disabled={createValueMutation.isPending}
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("products.variantAttributes.createVariant")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("products.variantAttributes.createVariantSubtitle")}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="variant_parent">{t("products.variantAttributes.field.parentProduct")}</Label>
            <Select id="variant_parent" value={variantParentId} onChange={(e) => setVariantParentId(e.target.value)}>
              <option value="">—</option>
              {parentEligibleProducts.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="variant_sku">{t("products.field.ref")}</Label>
              <Input id="variant_sku" value={variantSku} onChange={(e) => setVariantSku(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="variant_name">{t("products.field.label")}</Label>
              <Input id="variant_name" value={variantName} onChange={(e) => setVariantName(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>{t("products.variantAttributes.field.attributeValues")}</Label>
            {selectedAttributeId ? (
              <div className="flex flex-wrap gap-1.5">
                {values.map((value) => {
                  const selected = variantValueIds.includes(value.id);
                  return (
                    <button
                      key={value.id}
                      type="button"
                      onClick={() =>
                        setVariantValueIds(selected ? variantValueIds.filter((id) => id !== value.id) : [...variantValueIds, value.id])
                      }
                    >
                      <Badge variant={selected ? "primary" : "outline"}>{value.value}</Badge>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">{t("products.variantAttributes.pickAttributeFirst")}</p>
            )}
          </div>
          <Button
            className="w-full"
            disabled={!variantParentId || !variantSku || !variantName || variantValueIds.length === 0 || createVariantMutation.isPending}
            onClick={() => createVariantMutation.mutate()}
          >
            {createVariantMutation.isPending ? t("products.variantAttributes.creatingVariant") : t("products.variantAttributes.createVariantAction")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
