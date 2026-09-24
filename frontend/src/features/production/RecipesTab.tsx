import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Beaker, CheckCircle2, FlaskConical, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
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
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  activateRecipe,
  archiveRecipe,
  createRecipe,
  getRecipeYieldSummary,
  listClassifications,
  listProducts,
  listRecipes,
  promoteRecipeToTrial,
  rejectRecipe,
  type Recipe,
  type RecipeStatus,
} from "./api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const lineSchema = z.object({
  component_product_id: z.string().min(1, "Required"),
  default_percentage: z.coerce.number().min(0).max(100),
  min_percentage: z.coerce.number().min(0).max(100),
  max_percentage: z.coerce.number().min(0).max(100),
  is_hard_limit: z.boolean(),
});
const newRecipeSchema = z.object({
  target_product_id: z.string().min(1, "Required"),
  target_moisture_percentage: z.coerce.number().min(0).max(100).optional(),
  lines: z.array(lineSchema).min(1, "Add at least one component"),
});
type NewRecipeForm = z.infer<typeof newRecipeSchema>;

const QUERY_KEY = ["production", "recipes"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const CLASSIFICATIONS_QUERY_KEY = ["production", "product-classifications"] as const;
type StatusFilter = "all" | RecipeStatus;

const STATUS_VARIANT: Record<RecipeStatus, BadgeProps["variant"]> = {
  draft: "default",
  trial: "warning",
  active: "success",
  archived: "outline",
};

export function RecipesTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const STATUS_LABEL: Record<RecipeStatus, string> = {
    draft: t("production.recipes.status.draft"),
    trial: t("production.recipes.status.trial"),
    active: t("production.recipes.status.active"),
    archived: t("production.recipes.status.archived"),
  };

  const { data: recipes = [], isLoading } = useQuery({ queryKey: QUERY_KEY, queryFn: () => listRecipes(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: classifications = [] } = useQuery({ queryKey: CLASSIFICATIONS_QUERY_KEY, queryFn: () => listClassifications(token) });
  // Classifications key products by sku (production.product_classifications is
  // independent of core.products), but the pickers below submit product.id since
  // that's what warehouse stock operations (issue/receive) require — so match
  // classification.product_id against product.sku, not product.id.
  const finishedGoodIds = new Set(classifications.filter((c) => c.category === "finished_good").map((c) => c.product_id));
  const rawMaterialIds = new Set(classifications.filter((c) => c.category === "raw_material").map((c) => c.product_id));
  const regrindIds = new Set(classifications.filter((c) => c.category === "raw_material" && c.is_regrind).map((c) => c.product_id));
  const finishedGoodProducts = products.filter((p) => finishedGoodIds.has(p.sku));
  const recipeComponentProducts = products.filter((p) => {
    if (!rawMaterialIds.has(p.sku)) return false;
    const searchableName = `${p.sku} ${p.name}`.toLowerCase();
    return regrindIds.has(p.sku) || searchableName.includes("semoule") || searchableName.includes("mp");
  });

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewRecipeForm>({
    resolver: zodResolver(newRecipeSchema),
    defaultValues: {
      target_product_id: "",
      lines: [{ component_product_id: "", default_percentage: 100, min_percentage: 0, max_percentage: 100, is_hard_limit: false }],
    },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });

  const createMutation = useMutation({
    mutationFn: (input: NewRecipeForm) => createRecipe(token, input),
    onSuccess: (recipe) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset({
        target_product_id: "",
        lines: [{ component_product_id: "", default_percentage: 100, min_percentage: 0, max_percentage: 100, is_hard_limit: false }],
      });
      toast.success(t("production.recipes.created"), { description: `${recipe.target_product_id} · v${recipe.version}` });
    },
    onError: (error) => {
      toast.error(t("production.recipes.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const promoteMutation = useMutation({
    mutationFn: (id: string) => promoteRecipeToTrial(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.recipes.promoted"));
    },
    onError: (error) => toast.error(t("production.recipes.promoteError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectRecipe(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.recipes.rejected"));
    },
    onError: (error) => toast.error(t("production.recipes.rejectError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => activateRecipe(token, id),
    onSuccess: (recipe) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.recipes.activated"), { description: `${recipe.target_product_id} · v${recipe.version} ${t("production.recipes.activatedLive")}` });
    },
    onError: (error) => toast.error(t("production.recipes.activateError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) => archiveRecipe(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.recipes.archived"));
    },
    onError: (error) => toast.error(t("production.recipes.archiveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const activeCount = recipes.filter((r) => r.status === "active").length;
  const trialCount = recipes.filter((r) => r.status === "trial").length;
  const statusFilteredRecipes = statusFilter === "all" ? recipes : recipes.filter((r) => r.status === statusFilter);

  const columnFilterFields: FilterField<Recipe>[] = [
    { key: "target_product_id", kind: "text", getValue: (r) => r.target_product_id },
    { key: "version", kind: "range", getValue: (r) => r.version },
    { key: "components", kind: "range", getValue: (r) => r.lines.length },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredRecipes = columnFilters.apply(statusFilteredRecipes);

  const yieldQueries = useQueries({
    queries: filteredRecipes.map((recipe) => ({
      queryKey: ["production", "recipe-yield-summary", recipe.id],
      queryFn: () => getRecipeYieldSummary(token, recipe.id),
    })),
  });
  const averageYieldByRecipeId = new Map(
    filteredRecipes.map((recipe, i) => [recipe.id, yieldQueries[i]?.data?.average_yield_ratio ?? null]),
  );

  const columns: ColumnDef<Recipe>[] = [
    {
      key: "target_product_id",
      header: t("production.recipes.column.targetProduct"),
      defaultWidth: 200,
      cell: (recipe) => <span className="font-medium">{recipe.target_product_id}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.target_product_id ?? "",
        onChange: (v) => columnFilters.setTextValue("target_product_id", v),
        placeholder: t("production.recipes.column.targetProduct"),
      },
      sortValue: (recipe) => recipe.target_product_id,
    },
    {
      key: "version",
      header: t("production.recipes.column.version"),
      defaultWidth: 120,
      cell: (recipe) => <span className="tabular-nums text-muted-foreground">v{recipe.version}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.version?.min ?? "",
        max: columnFilters.range.version?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("version", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("version", "max", v),
      },
      sortValue: (recipe) => recipe.version,
    },
    {
      key: "status",
      header: t("production.recipes.column.status"),
      defaultWidth: 140,
      cell: (recipe) => (
        <Badge variant={STATUS_VARIANT[recipe.status]} dot>
          {STATUS_LABEL[recipe.status]}
        </Badge>
      ),
      sortValue: (recipe) => recipe.status,
    },
    {
      key: "components",
      header: t("production.recipes.column.components"),
      defaultWidth: 160,
      cell: (recipe) => (
        <span className="text-muted-foreground">
          {recipe.lines.length} {recipe.lines.length === 1 ? t("production.recipes.component") : t("production.recipes.componentsPlural")}
        </span>
      ),
      filterCell: {
        type: "range",
        min: columnFilters.range.components?.min ?? "",
        max: columnFilters.range.components?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("components", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("components", "max", v),
      },
      sortValue: (recipe) => recipe.lines.length,
    },
    {
      key: "averageYield",
      header: t("production.recipes.column.averageYield"),
      defaultWidth: 160,
      cell: (recipe) => {
        const ratio = averageYieldByRecipeId.get(recipe.id) ?? null;
        return (
          <span className="tabular-nums text-muted-foreground">
            {ratio !== null ? `${(ratio * 100).toFixed(1)}%` : t("production.workOrders.yieldNotAvailable")}
          </span>
        );
      },
      sortValue: (recipe) => averageYieldByRecipeId.get(recipe.id) ?? null,
    },
    {
      key: "action",
      header: t("production.recipes.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (recipe) => (
        <div className="flex justify-end gap-2">
          {recipe.status === "draft" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => promoteMutation.mutate(recipe.id)}
              disabled={promoteMutation.isPending && promoteMutation.variables === recipe.id}
            >
              {promoteMutation.isPending && promoteMutation.variables === recipe.id
                ? t("production.recipes.promoting")
                : t("production.recipes.promote")}
            </Button>
          )}
          {recipe.status === "trial" && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => activateMutation.mutate(recipe.id)}
                disabled={activateMutation.isPending && activateMutation.variables === recipe.id}
              >
                {activateMutation.isPending && activateMutation.variables === recipe.id
                  ? t("production.recipes.activating")
                  : t("production.recipes.activate")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => rejectMutation.mutate(recipe.id)}
                disabled={rejectMutation.isPending && rejectMutation.variables === recipe.id}
              >
                {rejectMutation.isPending && rejectMutation.variables === recipe.id
                  ? t("production.recipes.rejecting")
                  : t("production.recipes.reject")}
              </Button>
            </>
          )}
          {recipe.status === "active" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => archiveMutation.mutate(recipe.id)}
              disabled={archiveMutation.isPending && archiveMutation.variables === recipe.id}
            >
              {archiveMutation.isPending && archiveMutation.variables === recipe.id
                ? t("production.recipes.archiving")
                : t("production.recipes.archive")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("production.recipes", columns);
  const sortedRecipes = sortRows(filteredRecipes);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.recipes.stat.total")} value={recipes.length} icon={<Beaker className="h-5 w-5" />} accent="primary" />
        <StatCard label={t("production.recipes.stat.active")} value={activeCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard label={t("production.recipes.stat.trial")} value={trialCount} icon={<FlaskConical className="h-5 w-5" />} accent="warning" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.recipes.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.recipes.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("production.recipes.status.draft") },
                { value: "trial", label: t("production.recipes.status.trial") },
                { value: "active", label: t("production.recipes.status.active") },
                { value: "archived", label: t("production.recipes.status.archived") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog
            open={dialogOpen}
            onOpenChange={setDialogOpen}
          >
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" />
                {t("production.recipes.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("production.recipes.dialog.title")}</DialogTitle>
                <DialogDescription>{t("production.recipes.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="target_product_id">{t("production.recipes.field.targetProduct")}</Label>
                  {/* target_product_id has a real FK to core.products (recipes_target_product_id_fkey) --
                      free text here used to reach the backend as-is and crash the request with an
                      unhandled ForeignKeyViolation, which the browser then misreported as CORS
                      blocked. Only a value that actually exists in this list can be submitted. */}
                  <Select id="target_product_id" {...register("target_product_id")}>
                    <option value="">—</option>
                    {finishedGoodProducts.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                  {errors.target_product_id && <p className="text-sm text-destructive">{errors.target_product_id.message}</p>}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="target_moisture_percentage">{t("production.recipes.field.moisture")}</Label>
                  <Input
                    id="target_moisture_percentage"
                    type="number"
                    step="any"
                    placeholder="e.g. 12.5"
                    {...register("target_moisture_percentage")}
                  />
                  {errors.target_moisture_percentage && (
                    <p className="text-sm text-destructive">{errors.target_moisture_percentage.message}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>{t("production.recipes.field.components")}</Label>
                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => append({ component_product_id: "", default_percentage: 0, min_percentage: 0, max_percentage: 100, is_hard_limit: false })}
                      >
                        <Plus className="h-3.5 w-3.5" />
                        {t("production.recipes.addLine")}
                      </Button>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <AnimatePresence initial={false}>
                      {fields.map((field, index) => (
                        <motion.div
                          key={field.id}
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.18 }}
                          className="flex items-start gap-2"
                        >
                          <Select className="flex-1" {...register(`lines.${index}.component_product_id` as const)}>
                            <option value="">—</option>
                            {recipeComponentProducts.map((product) => (
                              <option key={product.id} value={product.id}>
                                {product.name}
                              </option>
                            ))}
                          </Select>
                          <Input
                            type="number"
                            step="any"
                            className="w-20"
                            placeholder={t("production.recipes.field.defaultPct")}
                            title={t("production.recipes.field.defaultPct")}
                            {...register(`lines.${index}.default_percentage` as const)}
                          />
                          <Input
                            type="number"
                            step="any"
                            className="w-20"
                            placeholder={t("production.recipes.field.minPct")}
                            title={t("production.recipes.field.minPct")}
                            {...register(`lines.${index}.min_percentage` as const)}
                          />
                          <Input
                            type="number"
                            step="any"
                            className="w-20"
                            placeholder={t("production.recipes.field.maxPct")}
                            title={t("production.recipes.field.maxPct")}
                            {...register(`lines.${index}.max_percentage` as const)}
                          />
                          <label className="flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap px-1 text-xs text-muted-foreground">
                            <input type="checkbox" {...register(`lines.${index}.is_hard_limit` as const)} />
                            {t("production.recipes.hardLimit")}
                          </label>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={fields.length === 1}
                            onClick={() => remove(index)}
                            aria-label={t("production.recipes.removeLine")}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                  {errors.lines?.message && <p className="text-sm text-destructive">{errors.lines.message}</p>}
                </div>

                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("production.recipes.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("production.recipes.creating") : t("production.recipes.create")}
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
              {!isLoading && filteredRecipes.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Beaker className="h-5 w-5" />}
                      title={t("production.recipes.empty.title")}
                      description={t("production.recipes.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedRecipes.map((recipe, i) => (
                  <motion.tr
                    key={recipe.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(recipe)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
