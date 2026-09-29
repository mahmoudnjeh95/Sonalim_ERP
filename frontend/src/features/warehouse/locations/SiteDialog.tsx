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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { createSite, updateSite, SITES_QUERY_KEY, type Site } from "./api";

const siteSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  address: z.string().optional(),
});
type SiteForm = z.infer<typeof siteSchema>;

export function SiteDialog({
  open,
  onOpenChange,
  site,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null creates a new site; a Site edits it in place. */
  site: Site | null;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const form = useForm<SiteForm>({ resolver: zodResolver(siteSchema), defaultValues: { code: "", name: "", address: "" } });

  useEffect(() => {
    if (open) form.reset({ code: site?.code ?? "", name: site?.name ?? "", address: site?.address ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, site]);

  const createMutation = useMutation({
    mutationFn: (input: SiteForm) => createSite(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SITES_QUERY_KEY });
      onOpenChange(false);
    },
  });
  const updateMutation = useMutation({
    mutationFn: (input: SiteForm) => updateSite(token, site!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SITES_QUERY_KEY });
      onOpenChange(false);
    },
  });
  const mutation = site ? updateMutation : createMutation;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{site ? t("warehouse.sites.dialog.edit.title") : t("warehouse.sites.dialog.create.title")}</DialogTitle>
          <DialogDescription>
            {site ? t("warehouse.sites.dialog.edit.description") : t("warehouse.sites.dialog.create.description")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => mutation.mutate(input))}>
          <div className="space-y-1.5">
            <Label htmlFor="site-code">{t("warehouse.sites.field.code")}</Label>
            <Input id="site-code" placeholder="e.g. main" {...form.register("code")} />
            {form.formState.errors.code && <p className="text-sm text-destructive">{form.formState.errors.code.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="site-name">{t("warehouse.sites.field.name")}</Label>
            <Input id="site-name" placeholder="e.g. Site principal" {...form.register("name")} />
            {form.formState.errors.name && <p className="text-sm text-destructive">{form.formState.errors.name.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="site-address">{t("warehouse.sites.field.address")}</Label>
            <Input id="site-address" {...form.register("address")} />
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.sites.dialog.error")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {site ? t("warehouse.sites.dialog.save") : t("warehouse.sites.dialog.create.submit")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
