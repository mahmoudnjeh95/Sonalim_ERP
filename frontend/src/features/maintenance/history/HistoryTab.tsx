import { useRef } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Select } from "../../../components/ui/select";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { apiErrorMessage } from "../jobs/jobFormat";
import { useHistoryIndicators, type MachineIndicators } from "./api";
import { usePeriod } from "./historyPeriod";
import { IndicatorsView } from "./IndicatorsView";
import { JournalView } from "./JournalView";
import { PeriodControl } from "./PeriodControl";

type HistoryView = "indicators" | "journal";

/**
 * Maintenance → Historique: per-machine indicators (production and maintenance side by side)
 * or the journal of closed interventions. Period, machine and view live in the URL.
 */
export function HistoryTab() {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { period } = usePeriod();
  const view: HistoryView = searchParams.get("view") === "journal" ? "journal" : "indicators";
  const equipmentId = searchParams.get("equipment") ?? "";

  const indicators = useHistoryIndicators(token, period);
  // The branded loader shows once, on the tab's first load; a period change after that uses skeletons.
  const loadedOnce = useRef(false);
  if (indicators.data) loadedOnce.current = true;
  const firstLoad = indicators.isLoading && !loadedOnce.current;
  const machines = (indicators.data?.machines ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));

  function update(key: string, value: string | null) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === null) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );
  }

  function openMachine(machine: MachineIndicators) {
    navigate(`/maintenance/equipment/${machine.equipment_id}?from=${period.from}&to=${period.to}`, {
      state: { from: `${location.pathname}${location.search}` },
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterTabs<HistoryView>
          options={[
            { value: "indicators", label: t("maintenance.history.view.indicators") },
            { value: "journal", label: t("maintenance.history.view.journal") },
          ]}
          value={view}
          onChange={(value) => update("view", value === "indicators" ? null : value)}
        />
        <div className="w-full sm:w-64">
          <Select
            aria-label={t("maintenance.history.machine.label")}
            value={equipmentId}
            onChange={(event) => update("equipment", event.target.value || null)}
          >
            <option value="">{t("maintenance.history.machine.all")}</option>
            {machines.map((machine) => (
              <option key={machine.equipment_id} value={machine.equipment_id}>
                {machine.code} — {machine.name}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <PeriodControl />

      {firstLoad ? (
        <AppLoader className="py-16" />
      ) : indicators.isError ? (
        <EmptyState
          icon={<AlertTriangle className="h-5 w-5" />}
          title={t("maintenance.history.loadError")}
          description={apiErrorMessage(indicators.error, t("maintenance.history.loadError"))}
        />
      ) : view === "indicators" ? (
        <IndicatorsView
          data={indicators.data}
          isLoading={indicators.isFetching && !indicators.data}
          equipmentId={equipmentId}
          onOpen={openMachine}
        />
      ) : (
        <JournalView period={period} equipmentId={equipmentId} />
      )}
    </div>
  );
}
