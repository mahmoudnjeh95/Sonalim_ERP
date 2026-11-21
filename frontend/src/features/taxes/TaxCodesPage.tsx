import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Percent, Plus } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { ProductSelect } from "../../components/patterns/ProductSelect";
import { listPartners } from "../partners/api";
import { useProductCatalog } from "../products/catalog";
import {
  TAX_KEYS,
  createTaxCode,
  getPartnerTaxCodes,
  getProductTaxCodes,
  listTaxCodes,
  setPartnerTaxCodes,
  setProductTaxCodes,
  taxCodeLabel,
  updateTaxCode,
  type TaxAssignment,
  type TaxCode,
  type TaxScope,
  type TaxSide,
} from "./api";

export const MANAGE_TAX_CODES = "core.manage_tax_codes";
const SCOPES: TaxScope[] = ["both", "sales", "purchases"];
const SCOPE_KEYS: Record<TaxScope, TranslationKey> = {
  both: "taxes.scope.both",
  sales: "taxes.scope.sales",
  purchases: "taxes.scope.purchases",
};

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : undefined);

/** The tenant's tax codes (rates and exemptions), and which code a product or a partner is taxed under. */
export function TaxCodesPage() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const canManage = hasPermission(MANAGE_TAX_CODES);
  const [editing, setEditing] = useState<TaxCode | "new" | null>(null);
  const { data: codes = [], isLoading } = useQuery({ queryKey: TAX_KEYS.codes(true), queryFn: () => listTaxCodes(token, true) });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("taxes.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("taxes.subtitle")}</p>
        </div>
        {canManage && (
          <Button onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" />
            {t("taxes.new")}
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("taxes.codesTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("taxes.column.code")}</TableHead>
                <TableHead>{t("taxes.column.name")}</TableHead>
                <TableHead className="text-right">{t("taxes.column.rate")}</TableHead>
                <TableHead>{t("taxes.column.scope")}</TableHead>
                <TableHead>{t("taxes.column.mention")}</TableHead>
                <TableHead>{t("taxes.column.status")}</TableHead>
                {canManage && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    {t("taxes.loading")}
                  </TableCell>
                </TableRow>
              )}
              {codes.map((code) => (
                <TableRow key={code.id} className={code.active ? undefined : "opacity-60"}>
                  <TableCell className="font-mono">{code.code}</TableCell>
                  <TableCell>{language === "fr" ? code.name_fr : code.name_en}</TableCell>
                  <TableCell className="text-right tabular-nums">{Number(code.rate)} %</TableCell>
                  <TableCell>
                    {t(SCOPE_KEYS[code.scope])}
                    {code.exempt && (
                      <Badge variant="outline" className="ml-2">
                        {t("taxes.exempt")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-muted-foreground">{code.legal_mention ?? "—"}</TableCell>
                  <TableCell>{code.active ? t("taxes.active") : t("taxes.inactive")}</TableCell>
                  {canManage && (
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" aria-label={t("taxes.edit")} onClick={() => setEditing(code)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="px-4 pt-3 text-xs text-muted-foreground">{t("taxes.accountsHint")}</p>
        </CardContent>
      </Card>

      <AssignmentsCard codes={codes.filter((code) => code.active)} canManage={canManage} />

      {editing && <TaxCodeDialog code={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function AssignmentsCard({ codes, canManage }: { codes: TaxCode[]; canManage: boolean }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { catalog } = useProductCatalog();
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const [productId, setProductId] = useState("");
  const [partnerId, setPartnerId] = useState("");
  const product = useQuery({
    queryKey: TAX_KEYS.product(productId),
    queryFn: () => getProductTaxCodes(token, productId),
    enabled: Boolean(productId),
  });
  const partner = useQuery({
    queryKey: TAX_KEYS.partner(partnerId),
    queryFn: () => getPartnerTaxCodes(token, partnerId),
    enabled: Boolean(partnerId),
  });
  const save = useMutation({
    mutationFn: ({ target, body }: { target: "product" | "partner"; body: Partial<TaxAssignment> }) =>
      target === "product" ? setProductTaxCodes(token, productId, body) : setPartnerTaxCodes(token, partnerId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TAX_KEYS.all });
      toast.success(t("taxes.assignment.saved"));
    },
    onError: (error) => toast.error(t("taxes.assignment.saveError"), { description: errorText(error) }),
  });

  const codeSelect = (target: "product" | "partner", side: TaxSide, assignment: TaxAssignment | undefined, noneKey: TranslationKey) => {
    const key = side === "sales" ? "sales_tax_code_id" : "purchases_tax_code_id";
    return (
      <Select
        aria-label={t(side === "sales" ? "taxes.assignment.sales" : "taxes.assignment.purchases")}
        value={assignment?.[key] ?? ""}
        disabled={!canManage || !assignment || save.isPending}
        onChange={(event) => save.mutate({ target, body: { [key]: event.target.value || null } })}
      >
        <option value="">{t(noneKey)}</option>
        {codes
          .filter((code) => code.scope === "both" || code.scope === side)
          .map((code) => (
            <option key={code.id} value={code.id}>
              {taxCodeLabel(code)}
            </option>
          ))}
      </Select>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("taxes.assignment.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("taxes.assignment.subtitle")}</p>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-2">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="tax_partner">{t("taxes.assignment.partner")}</Label>
            <Select id="tax_partner" value={partnerId} onChange={(event) => setPartnerId(event.target.value)}>
              <option value="">—</option>
              {partners.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                </option>
              ))}
            </Select>
          </div>
          {partnerId && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-muted-foreground">{t("taxes.assignment.asCustomer")}</span>
                {codeSelect("partner", "sales", partner.data, "taxes.assignment.followProduct")}
              </div>
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-muted-foreground">{t("taxes.assignment.asSupplier")}</span>
                {codeSelect("partner", "purchases", partner.data, "taxes.assignment.followProduct")}
              </div>
            </div>
          )}
        </div>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="tax_product">{t("taxes.assignment.product")}</Label>
            <ProductSelect id="tax_product" products={catalog} value={productId} onChange={(event) => setProductId(event.target.value)} />
          </div>
          {productId && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-muted-foreground">{t("taxes.assignment.sales")}</span>
                {codeSelect("product", "sales", product.data, "taxes.assignment.useDefault")}
              </div>
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-muted-foreground">{t("taxes.assignment.purchases")}</span>
                {codeSelect("product", "purchases", product.data, "taxes.assignment.useDefault")}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function TaxCodeDialog({ code, onClose }: { code: TaxCode | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const schema = useMemo(
    () =>
      z
        .object({
          code: z.string().trim().regex(/^[A-Za-z0-9._-]{1,20}$/, t("taxes.codeInvalid")),
          name_fr: z.string().trim().min(1, t("common.required")),
          name_en: z.string().trim(),
          rate: z.coerce.number().min(0).max(100),
          scope: z.enum(["both", "sales", "purchases"]),
          exempt: z.boolean(),
          legal_mention: z.string().trim(),
          active: z.boolean(),
        })
        .refine((form) => !form.exempt || form.rate === 0, { path: ["rate"], message: t("taxes.exemptRate") }),
    [t],
  );
  type TaxCodeForm = z.infer<typeof schema>;
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TaxCodeForm>({
    resolver: zodResolver(schema),
    defaultValues: code
      ? {
          code: code.code,
          name_fr: code.name_fr,
          name_en: code.name_en,
          rate: Number(code.rate),
          scope: code.scope,
          exempt: code.exempt,
          legal_mention: code.legal_mention ?? "",
          active: code.active,
        }
      : { code: "", name_fr: "", name_en: "", rate: 18, scope: "both", exempt: false, legal_mention: "", active: true },
  });
  const mutation = useMutation({
    mutationFn: (form: TaxCodeForm) => {
      const body = {
        name_fr: form.name_fr,
        name_en: form.name_en || null,
        rate: form.rate,
        scope: form.scope,
        exempt: form.exempt,
        legal_mention: form.legal_mention || null,
      };
      return code ? updateTaxCode(token, code.id, { ...body, legal_mention: form.legal_mention, active: form.active }) : createTaxCode(token, { ...body, code: form.code });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TAX_KEYS.all });
      toast.success(t(code ? "taxes.updated" : "taxes.created"));
      onClose();
    },
    onError: (error) => toast.error(t("taxes.saveError"), { description: errorText(error) }),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(code ? "taxes.editTitle" : "taxes.newTitle")}</DialogTitle>
          <DialogDescription>{t("taxes.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((form) => mutation.mutate(form))}>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="tax_code">{t("taxes.column.code")}</Label>
              {/* readOnly, not disabled: lines, events and posting rules refer to the code, so it never changes. */}
              <Input id="tax_code" readOnly={code !== null} {...register("code")} />
              {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tax_rate">{t("taxes.column.rate")}</Label>
              <Input id="tax_rate" type="number" step="0.01" min={0} max={100} {...register("rate")} />
              {errors.rate && <p className="text-sm text-destructive">{errors.rate.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tax_scope">{t("taxes.column.scope")}</Label>
              <Select id="tax_scope" {...register("scope")}>
                {SCOPES.map((scope) => (
                  <option key={scope} value={scope}>
                    {t(SCOPE_KEYS[scope])}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="tax_name_fr">{t("taxes.nameFr")}</Label>
              <Input id="tax_name_fr" {...register("name_fr")} />
              {errors.name_fr && <p className="text-sm text-destructive">{errors.name_fr.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tax_name_en">{t("taxes.nameEn")}</Label>
              <Input id="tax_name_en" {...register("name_en")} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tax_mention">{t("taxes.column.mention")}</Label>
            <Input id="tax_mention" placeholder={t("taxes.mentionPlaceholder")} {...register("legal_mention")} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4" {...register("exempt")} />
            {t("taxes.exemptHint")}
          </label>
          {code && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4" {...register("active")} />
              {t("taxes.activeHint")}
            </label>
          )}
          {code && <p className="text-xs text-muted-foreground">{t("taxes.rateChangeHint")}</p>}
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            <Percent className="h-4 w-4" />
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
