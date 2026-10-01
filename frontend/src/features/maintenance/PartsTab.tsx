import { useState } from "react";
import { PackageSearch } from "lucide-react";
import { Card, CardContent } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { usePartRequests, type PartRequest } from "./api";
import { useHasPermission } from "./hooks";
import { PartRequestCard } from "./parts/PartRequestCard";
import { SparePartsLocationCard } from "./parts/SparePartsLocationCard";

const STATUS_FILTERS = ["pending", "approved", "rejected"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const STATUS_FILTER_LABEL_KEY: Record<StatusFilter, TranslationKey> = {
  pending: "maintenance.jobs.parts.status.pending",
  approved: "maintenance.jobs.parts.status.approved",
  rejected: "maintenance.jobs.parts.status.rejected",
};

/**
 * The Parts tab: every spare-parts request, filtered by status
 * (En attente / Approuvées / Refusées). A supervisor (`maintenance.plan_jobs`)
 * can decide a pending one straight from its card (Valider opens
 * `ApproveDialog`, Refuser a short note dialog), and picks the warehouse
 * location spare parts are kept in.
 */
export function PartsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const canDecide = useHasPermission("maintenance.plan_jobs");

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const { data: requests, isLoading } = usePartRequests(token, statusFilter);

  return (
    <div className="space-y-4">
      {canDecide && <SparePartsLocationCard />}
      <FilterTabs
        options={STATUS_FILTERS.map((status) => ({ value: status, label: t(STATUS_FILTER_LABEL_KEY[status]) }))}
        value={statusFilter}
        onChange={setStatusFilter}
      />

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : !requests || requests.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={<PackageSearch className="h-5 w-5" />}
              title={t("maintenance.parts.empty.title")}
              description={t("maintenance.parts.empty.description")}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {requests.map((request: PartRequest) => (
            <PartRequestCard key={request.id} request={request} canDecide={canDecide} />
          ))}
        </div>
      )}
    </div>
  );
}
