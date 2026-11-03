import { Warehouse } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent } from "../../../components/ui/card";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useLocationOptions, useMaintenanceSettings, useUpdateMaintenanceSettings } from "../api";
import { apiErrorMessage } from "../jobs/jobFormat";

/**
 * The supervisor's one-time choice of the warehouse location spare parts are
 * kept in (its shelves count too). Points list parts from it, a check shows its
 * stock, and the parts approval offers it first. Saved as soon as it is picked.
 */
export function SparePartsLocationCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const { data: settings, isLoading: settingsLoading } = useMaintenanceSettings(token);
  const { data: options = [], isLoading: optionsLoading } = useLocationOptions(token);
  const update = useUpdateMaintenanceSettings(token);

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Warehouse className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <Label htmlFor="spare-parts-location">{t("maintenance.parts.location.title")}</Label>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("maintenance.parts.location.hint")}</p>
          </div>
        </div>
        {settingsLoading || optionsLoading ? (
          <Skeleton className="h-10 w-full sm:w-72" />
        ) : (
          <Select
            id="spare-parts-location"
            className="w-full sm:w-72"
            value={settings?.spare_parts_location_id ?? ""}
            disabled={update.isPending}
            onChange={(event) =>
              update.mutate(
                { spare_parts_location_id: event.target.value || null },
                {
                  onSuccess: () => toast.success(t("maintenance.parts.location.saved")),
                  onError: (error) => toast.error(apiErrorMessage(error, t("maintenance.parts.location.error"))),
                },
              )
            }
          >
            <option value="">{t("maintenance.parts.location.none")}</option>
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
      </CardContent>
    </Card>
  );
}
