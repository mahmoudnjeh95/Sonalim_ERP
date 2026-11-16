import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Label } from "../../../components/ui/label";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { listSites, getLocationTree, locationTreeQueryKey, SITES_QUERY_KEY } from "../locations/api";
import { createCycleCount, CYCLE_COUNTS_QUERY_KEY, type CycleCountMode, type CycleCountType } from "./api";

export function NewCycleCountDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: sites = [] } = useQuery({ queryKey: SITES_QUERY_KEY, queryFn: () => listSites(token) });
  const [siteId, setSiteId] = useState("");
  const [scopeLocationId, setScopeLocationId] = useState("");
  const [countType, setCountType] = useState<CycleCountType>("scheduled");
  const [scheduledFor, setScheduledFor] = useState("");
  const [mode, setMode] = useState<CycleCountMode>("full");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (open) {
      setSiteId(sites[0]?.id ?? "");
      setScopeLocationId("");
      setCountType("scheduled");
      setScheduledFor("");
      setMode("full");
      setNote("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sites]);

  const { data: locations = [] } = useQuery({
    queryKey: siteId ? locationTreeQueryKey(siteId) : ["warehouse", "locations", "tree", "none"],
    queryFn: () => getLocationTree(token, siteId),
    enabled: open && siteId !== "",
  });

  const mutation = useMutation({
    mutationFn: () =>
      createCycleCount(token, {
        site_id: siteId,
        scope_location_id: scopeLocationId || null,
        count_type: countType,
        scheduled_for: scheduledFor || null,
        mode,
        note: note || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CYCLE_COUNTS_QUERY_KEY });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("warehouse.cycleCounts.dialog.create.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.cycleCounts.dialog.create.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="cc-mode">{t("warehouse.cycleCounts.field.mode")}</Label>
            <Select id="cc-mode" value={mode} onChange={(event) => setMode(event.target.value as CycleCountMode)}>
              <option value="full">{t("warehouse.cycleCounts.mode.full")}</option>
              <option value="interim">{t("warehouse.cycleCounts.mode.interim")}</option>
            </Select>
            <p className="text-xs text-muted-foreground">{t(`warehouse.cycleCounts.mode.${mode}.hint`)}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-site">{t("warehouse.cycleCounts.field.site")}</Label>
            <Select id="cc-site" value={siteId} onChange={(event) => { setSiteId(event.target.value); setScopeLocationId(""); }}>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name} ({site.code})
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-scope">{t("warehouse.cycleCounts.field.scope")}</Label>
            <Select id="cc-scope" value={scopeLocationId} onChange={(event) => setScopeLocationId(event.target.value)}>
              <option value="">{t("warehouse.cycleCounts.field.scope.wholeSite")}</option>
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name} ({location.code})
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-type">{t("warehouse.cycleCounts.field.countType")}</Label>
            <Select id="cc-type" value={countType} onChange={(event) => setCountType(event.target.value as CycleCountType)}>
              <option value="scheduled">{t("warehouse.cycleCounts.type.scheduled")}</option>
              <option value="blind">{t("warehouse.cycleCounts.type.blind")}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-scheduled">{t("warehouse.cycleCounts.field.scheduledFor")}</Label>
            <Input id="cc-scheduled" type="date" value={scheduledFor} onChange={(event) => setScheduledFor(event.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-note">{t("voucher.note")}</Label>
            <Input id="cc-note" value={note} onChange={(event) => setNote(event.target.value)} />
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.cycleCounts.dialog.error")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending || !siteId}>
            {t("warehouse.cycleCounts.dialog.create.submit")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
