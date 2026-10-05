import { useRef } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowLeft, Printer } from "lucide-react";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import type { EquipmentStatus } from "../api";
import { apiErrorMessage } from "../jobs/jobFormat";
import { useEquipmentHistory } from "./api";
import { CheckpointHistorySheet } from "./CheckpointHistorySheet";
import { CheckpointList } from "./CheckpointList";
import { fill } from "./historyFormat";
import { usePeriod } from "./historyPeriod";
import { HistoryTimeline } from "./HistoryTimeline";
import { IndicatorBlocks } from "./IndicatorBlocks";
import { MachinePhotoTile } from "./MachinePhoto";
import { PeriodControl } from "./PeriodControl";

const STATUS_VARIANT: Record<EquipmentStatus, BadgeProps["variant"]> = {
  operational: "success",
  down: "destructive",
  maintenance: "warning",
};

/** /maintenance/equipment/:equipmentId — one machine's logbook (spec 2026-10-02 maintenance history). */
export function EquipmentHistoryPage() {
  const { equipmentId = "" } = useParams();
  const { session } = useAuth();
  const { t } = useI18n();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { period } = usePeriod();
  const history = useEquipmentHistory(session!.token, equipmentId, period);
  const backTo = (location.state as { from?: string } | null)?.from ?? "/maintenance?tab=history";
  const loadedOnce = useRef(false);
  if (history.data) loadedOnce.current = true;

  if (history.isLoading && !loadedOnce.current) return <AppLoader className="py-24" />;
  if (!history.data) {
    return (
      <EmptyState
        icon={<AlertTriangle className="h-5 w-5" />}
        title={t("maintenance.history.logbook.notFound")}
        description={apiErrorMessage(history.error, t("maintenance.history.loadError"))}
        action={
          <Button variant="outline" asChild>
            <Link to={backTo}>{t("maintenance.history.logbook.back")}</Link>
          </Button>
        }
      />
    );
  }

  const data = history.data;
  const machine = data.equipment;
  const pointId = searchParams.get("point");
  const jobs = data.timeline.filter((item) => item.kind === "job").length;
  const stops = data.timeline.filter((item) => item.kind === "production_stop").length;

  function openPoint(checkpointId: string | null) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (checkpointId) next.set("point", checkpointId);
        else next.delete("point");
        return next;
      },
      { replace: true },
    );
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" asChild>
        <Link to={backTo}>
          <ArrowLeft className="h-4 w-4" />
          {t("maintenance.history.logbook.back")}
        </Link>
      </Button>

      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <Card className="grid items-center gap-4 p-3 sm:grid-cols-[200px_1fr] lg:grid-cols-[200px_1fr_auto]">
          <MachinePhotoTile machine={machine} caption={t("maintenance.history.logbook.photoCaption")} className="h-40 sm:h-32" />
          <div className="min-w-0 space-y-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              {t("maintenance.history.logbook.eyebrow")}
            </p>
            <h1 className="break-words text-xl font-bold tracking-tight">{machine.name}</h1>
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="primary">{machine.code}</Badge>
              {machine.production_stage && <Badge>{t(`maintenance.equipment.stage.${machine.production_stage}` as TranslationKey)}</Badge>}
              {machine.archived_at ? (
                <Badge variant="outline" dot>
                  {t("maintenance.equipment.archived.badge")}
                </Badge>
              ) : (
                <Badge variant={STATUS_VARIANT[machine.status]} dot>
                  {t(`maintenance.equipment.status.${machine.status}` as TranslationKey)}
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{fill(t("maintenance.history.logbook.summary"), { jobs, stops })}</p>
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2 lg:col-span-1 lg:items-end">
            <PeriodControl />
            <Button asChild className="w-full sm:w-auto">
              <Link to={`/maintenance/equipment/${equipmentId}/print?from=${period.from}&to=${period.to}`}>
                <Printer className="h-4 w-4" />
                {t("maintenance.history.logbook.print")}
              </Link>
            </Button>
          </div>
        </Card>
      </motion.div>

      <IndicatorBlocks
        production={data.indicators.production}
        maintenance={data.indicators.maintenance}
        costsVisible={data.costs_visible}
        productionAvailable={data.production_available}
      />

      <div className="grid gap-4 lg:grid-cols-[1.7fr_1fr]">
        <Card className="min-w-0">
          <HistoryTimeline items={data.timeline} />
        </Card>
        <Card className="min-w-0 self-start">
          <CheckpointList points={data.checkpoints} onOpen={openPoint} />
        </Card>
      </div>

      <CheckpointHistorySheet checkpointId={pointId} onClose={() => openPoint(null)} />
    </div>
  );
}
