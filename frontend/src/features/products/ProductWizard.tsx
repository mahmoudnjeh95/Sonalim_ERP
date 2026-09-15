import { useState } from "react";
import { useForm, type UseFormReturn } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { z } from "zod";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import type { TranslationKey } from "../../lib/i18n";
import type { UnitOfMeasure, Location } from "../warehouse/api";

type TFunc = (key: TranslationKey) => string;

function blankToUndefined<T extends z.ZodTypeAny>(schema: T) {
  return z.preprocess((value) => (value === "" || value === null ? undefined : value), schema);
}

export const productWizardSchema = z.object({
  // Step 1: Identity
  sku: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  product_type: z.enum(["PL", "PC"], { errorMap: () => ({ message: "Required" }) }),
  product_family: z.string().optional(),
  uom_id: z.string().min(1, "Required"),
  description: z.string().optional(),

  // Step 2: Pricing & Weight
  net_weight_grams: blankToUndefined(z.coerce.number().positive().optional()),
  selling_price: blankToUndefined(z.coerce.number().min(0).optional()),
  min_selling_price: blankToUndefined(z.coerce.number().min(0).optional()),
  purchase_price: blankToUndefined(z.coerce.number().min(0).optional()),
  tax_rate: blankToUndefined(z.coerce.number().min(0).optional()),

  // Step 3: Packaging
  empty_packaging_weight_grams: blankToUndefined(z.coerce.number().positive().optional()),
  sachets_per_package: blankToUndefined(z.coerce.number().positive().optional()),
  packets_per_carton: blankToUndefined(z.coerce.number().positive().optional()),
  carton_weight_grams: blankToUndefined(z.coerce.number().positive().optional()),
  cartons_per_pallet: blankToUndefined(z.coerce.number().positive().optional()),

  // Step 4: Settings
  is_sellable: z.enum(["true", "false"]),
  is_purchasable: z.enum(["true", "false"]),
  lot_serial_tracking: z.enum(["none", "lot", "serial"]),
  expiry_date_policy: z.enum(["none", "sell_by", "eat_by"]),
  default_location_id: z.string().optional(),
  stock_alert_threshold: blankToUndefined(z.coerce.number().min(0).optional()),
  internal_note: z.string().optional(),
  accounting_code_sale: z.string().optional(),
  accounting_code_sale_export: z.string().optional(),
  accounting_code_purchase: z.string().optional(),
  accounting_code_purchase_import: z.string().optional(),
});

export type ProductWizardForm = z.infer<typeof productWizardSchema>;

export const WIZARD_EMPTY_DEFAULTS: ProductWizardForm = {
  sku: "",
  name: "",
  product_type: "PL",
  product_family: "",
  uom_id: "",
  description: "",
  net_weight_grams: undefined,
  selling_price: undefined,
  min_selling_price: undefined,
  purchase_price: undefined,
  tax_rate: undefined,
  empty_packaging_weight_grams: undefined,
  sachets_per_package: undefined,
  packets_per_carton: undefined,
  carton_weight_grams: undefined,
  cartons_per_pallet: undefined,
  is_sellable: "true",
  is_purchasable: "true",
  lot_serial_tracking: "none",
  expiry_date_policy: "none",
  default_location_id: "",
  stock_alert_threshold: undefined,
  internal_note: "",
  accounting_code_sale: "",
  accounting_code_sale_export: "",
  accounting_code_purchase: "",
  accounting_code_purchase_import: "",
};

interface ProductWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uoms: UnitOfMeasure[];
  locations: Location[];
  onSubmit: (data: ProductWizardForm) => void;
  isLoading?: boolean;
  t: TFunc;
}

type Step = 1 | 2 | 3 | 4;

export function ProductWizard({ open, onOpenChange, uoms, locations, onSubmit, isLoading = false, t }: ProductWizardProps) {
  const [currentStep, setCurrentStep] = useState<Step>(1);
  const form = useForm<ProductWizardForm>({
    resolver: zodResolver(productWizardSchema),
    defaultValues: WIZARD_EMPTY_DEFAULTS,
    mode: "onChange",
  });

  const handleNext = async () => {
    const fieldsToValidate = getFieldsForStep(currentStep);
    const isValid = await form.trigger(fieldsToValidate as any);

    if (isValid) {
      if (currentStep < 4) {
        setCurrentStep((currentStep + 1) as Step);
      } else {
        form.handleSubmit(onSubmit)();
      }
    }
  };

  const handlePrev = () => {
    if (currentStep > 1) {
      setCurrentStep((currentStep - 1) as Step);
    }
  };

  const handleClose = () => {
    setCurrentStep(1);
    form.reset(WIZARD_EMPTY_DEFAULTS);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("products.newProduct")} — Étape {currentStep}/4</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Step Indicator */}
          <div className="flex gap-2">
            {[1, 2, 3, 4].map((step) => (
              <div
                key={step}
                className={`h-2 flex-1 rounded-full transition-colors ${
                  step <= currentStep ? "bg-blue-500" : "bg-gray-300"
                }`}
              />
            ))}
          </div>

          {/* Step Content */}
          <div>
            {currentStep === 1 && <Step1Identity form={form} uoms={uoms} t={t} />}
            {currentStep === 2 && <Step2Pricing form={form} t={t} />}
            {currentStep === 3 && <Step3Packaging form={form} t={t} />}
            {currentStep === 4 && <Step4Settings form={form} locations={locations} t={t} />}
          </div>

          {/* Navigation */}
          <div className="flex justify-between pt-4 border-t">
            <Button
              variant="outline"
              onClick={handlePrev}
              disabled={currentStep === 1}
            >
              <ChevronLeft className="w-4 h-4 mr-2" />
              {t("common.previous")}
            </Button>

            <Button onClick={handleNext} disabled={isLoading}>
              {currentStep === 4 ? t("common.create") : t("common.next")}
              {currentStep < 4 && <ChevronRight className="w-4 h-4 ml-2" />}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function getFieldsForStep(step: Step): (keyof ProductWizardForm)[] {
  switch (step) {
    case 1:
      return ["sku", "name", "product_type", "product_family", "uom_id", "description"];
    case 2:
      return ["net_weight_grams", "selling_price", "min_selling_price", "purchase_price", "tax_rate"];
    case 3:
      return ["empty_packaging_weight_grams", "sachets_per_package", "packets_per_carton", "carton_weight_grams", "cartons_per_pallet"];
    case 4:
      return ["is_sellable", "is_purchasable", "lot_serial_tracking", "expiry_date_policy", "default_location_id", "stock_alert_threshold", "internal_note", "accounting_code_sale", "accounting_code_sale_export", "accounting_code_purchase", "accounting_code_purchase_import"];
    default:
      return [];
  }
}

// ============================================================================
// Step Components
// ============================================================================

function Step1Identity({ form, uoms, t }: { form: UseFormReturn<ProductWizardForm>; uoms: UnitOfMeasure[]; t: TFunc }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="sku">{t("products.field.ref")} *</Label>
          <Input
            id="sku"
            placeholder="e.g., SPAG-11-200G"
            {...form.register("sku")}
            error={form.formState.errors.sku?.message}
          />
        </div>
        <div>
          <Label htmlFor="name">{t("products.field.label")} *</Label>
          <Input
            id="name"
            placeholder="e.g., Spaghetti 1.1 200g"
            {...form.register("name")}
            error={form.formState.errors.name?.message}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="product_type">{t("products.field.type")} *</Label>
          <select
            id="product_type"
            {...form.register("product_type")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">— Select —</option>
            <option value="PL">Pâte Longues (PL)</option>
            <option value="PC">Pâte Courte (PC)</option>
          </select>
          {form.formState.errors.product_type && (
            <p className="mt-1 text-sm text-red-500">{form.formState.errors.product_type.message}</p>
          )}
        </div>
        <div>
          <Label htmlFor="uom_id">{t("products.field.uom")} *</Label>
          <select
            id="uom_id"
            {...form.register("uom_id")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">— Select UOM —</option>
            {uoms.map((uom) => (
              <option key={uom.id} value={uom.id}>
                {uom.name} ({uom.code})
              </option>
            ))}
          </select>
          {form.formState.errors.uom_id && (
            <p className="mt-1 text-sm text-red-500">{form.formState.errors.uom_id.message}</p>
          )}
        </div>
      </div>

      <div>
        <Label htmlFor="product_family">{t("products.field.family")} — {t("common.optional")}</Label>
        <Input
          id="product_family"
          placeholder="e.g., Spaghetti 1,1"
          {...form.register("product_family")}
        />
      </div>

      <div>
        <Label htmlFor="description">{t("products.field.description")}</Label>
        <Input
          id="description"
          placeholder="Optional description"
          {...form.register("description")}
        />
      </div>
    </div>
  );
}

function Step2Pricing({ form, t }: { form: UseFormReturn<ProductWizardForm>; t: TFunc }) {
  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="net_weight_grams">{t("products.field.netWeight")} (g) — {t("common.optional")}</Label>
        <Input
          id="net_weight_grams"
          type="number"
          step="0.01"
          placeholder="e.g., 200"
          {...form.register("net_weight_grams")}
          error={form.formState.errors.net_weight_grams?.message}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="selling_price">{t("products.field.sellingPrice")}</Label>
          <Input
            id="selling_price"
            type="number"
            step="0.01"
            placeholder="0"
            {...form.register("selling_price")}
            error={form.formState.errors.selling_price?.message}
          />
        </div>
        <div>
          <Label htmlFor="min_selling_price">{t("products.field.minSellingPrice")} — {t("common.optional")}</Label>
          <Input
            id="min_selling_price"
            type="number"
            step="0.01"
            placeholder="Optional"
            {...form.register("min_selling_price")}
            error={form.formState.errors.min_selling_price?.message}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="purchase_price">{t("products.field.purchasePrice")}</Label>
          <Input
            id="purchase_price"
            type="number"
            step="0.01"
            placeholder="0"
            {...form.register("purchase_price")}
            error={form.formState.errors.purchase_price?.message}
          />
        </div>
        <div>
          <Label htmlFor="tax_rate">{t("products.field.taxRate")} (%)</Label>
          <Input
            id="tax_rate"
            type="number"
            step="0.01"
            placeholder="0"
            {...form.register("tax_rate")}
            error={form.formState.errors.tax_rate?.message}
          />
        </div>
      </div>
    </div>
  );
}

function Step3Packaging({ form, t }: { form: UseFormReturn<ProductWizardForm>; t: TFunc }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">{t("common.optional")} — {t("products.help.packagingOptional")}</p>

      <div>
        <Label htmlFor="empty_packaging_weight_grams">{t("products.field.emptyPackagingWeight")} (g)</Label>
        <Input
          id="empty_packaging_weight_grams"
          type="number"
          step="0.01"
          placeholder="e.g., 3"
          {...form.register("empty_packaging_weight_grams")}
          error={form.formState.errors.empty_packaging_weight_grams?.message}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="sachets_per_package">{t("products.field.sachetsPerPackage")}</Label>
          <Input
            id="sachets_per_package"
            type="number"
            step="1"
            placeholder="e.g., 40"
            {...form.register("sachets_per_package")}
            error={form.formState.errors.sachets_per_package?.message}
          />
        </div>
        <div>
          <Label htmlFor="packets_per_carton">{t("products.field.packetsPerCarton")}</Label>
          <Input
            id="packets_per_carton"
            type="number"
            step="1"
            placeholder="e.g., 80"
            {...form.register("packets_per_carton")}
            error={form.formState.errors.packets_per_carton?.message}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="carton_weight_grams">{t("products.field.cartonWeight")} (g)</Label>
          <Input
            id="carton_weight_grams"
            type="number"
            step="0.01"
            placeholder="e.g., 10"
            {...form.register("carton_weight_grams")}
            error={form.formState.errors.carton_weight_grams?.message}
          />
        </div>
        <div>
          <Label htmlFor="cartons_per_pallet">{t("products.field.cartonsPerPallet")}</Label>
          <Input
            id="cartons_per_pallet"
            type="number"
            step="1"
            placeholder="e.g., 100"
            {...form.register("cartons_per_pallet")}
            error={form.formState.errors.cartons_per_pallet?.message}
          />
        </div>
      </div>
    </div>
  );
}

function Step4Settings({ form, locations, t }: { form: UseFormReturn<ProductWizardForm>; locations: Location[]; t: TFunc }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="is_sellable">{t("products.field.statusSell")}</Label>
          <select
            id="is_sellable"
            {...form.register("is_sellable")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="true">{t("products.status.sell")}</option>
            <option value="false">{t("products.status.notSell")}</option>
          </select>
        </div>
        <div>
          <Label htmlFor="is_purchasable">{t("products.field.statusPurchase")}</Label>
          <select
            id="is_purchasable"
            {...form.register("is_purchasable")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="true">{t("products.status.purchase")}</option>
            <option value="false">{t("products.status.notPurchase")}</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="lot_serial_tracking">{t("products.field.lotSerialTracking")}</Label>
          <select
            id="lot_serial_tracking"
            {...form.register("lot_serial_tracking")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="none">{t("products.lotTracking.none")}</option>
            <option value="lot">{t("products.lotTracking.lot")}</option>
            <option value="serial">{t("products.lotTracking.serial")}</option>
          </select>
        </div>
        <div>
          <Label htmlFor="expiry_date_policy">{t("products.field.expiryDatePolicy")}</Label>
          <select
            id="expiry_date_policy"
            {...form.register("expiry_date_policy")}
            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="none">{t("products.expiryPolicy.none")}</option>
            <option value="sell_by">{t("products.expiryPolicy.sellBy")}</option>
            <option value="eat_by">{t("products.expiryPolicy.eatBy")}</option>
          </select>
        </div>
      </div>

      <div>
        <Label htmlFor="default_location_id">{t("products.field.warehouse")} — {t("common.optional")}</Label>
        <select
          id="default_location_id"
          {...form.register("default_location_id")}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
        >
          <option value="">— {t("common.select")} —</option>
          {locations.map((loc) => (
            <option key={loc.id} value={loc.id}>
              {loc.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <Label htmlFor="stock_alert_threshold">{t("products.field.alertThreshold")} — {t("common.optional")}</Label>
        <Input
          id="stock_alert_threshold"
          type="number"
          step="0.01"
          placeholder="Optional"
          {...form.register("stock_alert_threshold")}
          error={form.formState.errors.stock_alert_threshold?.message}
        />
      </div>

      <div>
        <Label htmlFor="internal_note">{t("products.field.note")}</Label>
        <Input
          id="internal_note"
          placeholder="Internal notes (not visible on invoices)"
          {...form.register("internal_note")}
        />
      </div>

      <div className="border-t pt-4">
        <h3 className="text-sm font-semibold mb-4">{t("products.field.accountingCodes")}</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="accounting_code_sale">{t("products.field.accountingSale")} — {t("common.optional")}</Label>
            <Input
              id="accounting_code_sale"
              placeholder="e.g., 701000"
              {...form.register("accounting_code_sale")}
              error={form.formState.errors.accounting_code_sale?.message}
            />
          </div>
          <div>
            <Label htmlFor="accounting_code_sale_export">{t("products.field.accountingSaleExport")} — {t("common.optional")}</Label>
            <Input
              id="accounting_code_sale_export"
              placeholder="e.g., 701100"
              {...form.register("accounting_code_sale_export")}
              error={form.formState.errors.accounting_code_sale_export?.message}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 mt-4">
          <div>
            <Label htmlFor="accounting_code_purchase">{t("products.field.accountingPurchase")} — {t("common.optional")}</Label>
            <Input
              id="accounting_code_purchase"
              placeholder="e.g., 601000"
              {...form.register("accounting_code_purchase")}
              error={form.formState.errors.accounting_code_purchase?.message}
            />
          </div>
          <div>
            <Label htmlFor="accounting_code_purchase_import">{t("products.field.accountingPurchaseImport")} — {t("common.optional")}</Label>
            <Input
              id="accounting_code_purchase_import"
              placeholder="e.g., 601100"
              {...form.register("accounting_code_purchase_import")}
              error={form.formState.errors.accounting_code_purchase_import?.message}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
