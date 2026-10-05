import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import type { Location } from "../api";
import { createHierarchyLocation, locationTreeQueryKey } from "./api";

const LOCATION_TYPES = ["zone", "aisle", "rack", "bin"] as const;

const locationSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  location_type: z.enum(LOCATION_TYPES),
  parent_location_id: z.string(),
});
type LocationForm = z.infer<typeof locationSchema>;

export function LocationDialog({
  open,
  onOpenChange,
  siteId,
  locations,
  defaultParentId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  siteId: string;
  /** Every existing location in this site, offered as candidate parents. */
  locations: Location[];
  defaultParentId?: string | null;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const form = useForm<LocationForm>({
    resolver: zodResolver(locationSchema),
    defaultValues: { code: "", name: "", location_type: "bin", parent_location_id: "" },
  });

  useEffect(() => {
    if (open) form.reset({ code: "", name: "", location_type: "bin", parent_location_id: defaultParentId ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultParentId]);

  const mutation = useMutation({
    mutationFn: (input: LocationForm) =>
      createHierarchyLocation(token, {
        code: input.code,
        name: input.name,
        site_id: siteId,
        location_type: input.location_type,
        parent_location_id: input.parent_location_id || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: locationTreeQueryKey(siteId) });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("warehouse.locations.dialog.create.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.locations.dialog.create.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => mutation.mutate(input))}>
          <div className="space-y-1.5">
            <Label htmlFor="loc-h-code">{t("warehouse.locations.field.code")}</Label>
            <Input id="loc-h-code" {...form.register("code")} />
            {form.formState.errors.code && <p className="text-sm text-destructive">{form.formState.errors.code.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-h-name">{t("warehouse.locations.field.name")}</Label>
            <Input id="loc-h-name" {...form.register("name")} />
            {form.formState.errors.name && <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-h-type">{t("warehouse.locations.field.type")}</Label>
            <Select id="loc-h-type" {...form.register("location_type")}>
              {LOCATION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(`warehouse.locations.type.${type}`)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-h-parent">{t("warehouse.locations.field.parent")}</Label>
            <Select id="loc-h-parent" {...form.register("parent_location_id")}>
              <option value="">{t("warehouse.locations.field.parent.none")}</option>
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name} ({loc.code})
                </option>
              ))}
            </Select>
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.locations.dialog.error")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {t("warehouse.locations.dialog.create.submit")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
