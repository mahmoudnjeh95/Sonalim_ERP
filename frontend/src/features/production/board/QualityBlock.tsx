import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Skeleton } from "../../../components/ui/skeleton";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import InspectionSvg from "../../../assets/icons/quality/inspection.svg?react";
import NonconformitySvg from "../../../assets/icons/quality/nonconformity.svg?react";
import ReleaseSvg from "../../../assets/icons/quality/release.svg?react";
import QualityInspection from "../../../assets/illustrations/quality-inspection.svg?react";
import { listNonConformities, listQualityTeamPerformance } from "../../qc/api";
import { formatNumber } from "./boardFormat";
import { BlockError, MissingState } from "./BoardStates";

const InspectionIcon = outlineIcon(InspectionSvg);
const NonconformityIcon = outlineIcon(NonconformitySvg);
const ReleaseIcon = outlineIcon(ReleaseSvg);

const RING_LENGTH = 2 * Math.PI * 34;

function Card({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-white p-4 shadow-soft">
      <p className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </p>
      {children}
    </div>
  );
}

/**
 * Quality for the selected day, from what QC records: conformity of the
 * cartons inspected, and the non-conformities raised. Lot status at release is
 * not recorded per finished lot anywhere yet, so that card says so instead of
 * showing a figure.
 */
export function QualityBlock({ date }: { date: string }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const conformity = useQuery({
    queryKey: ["qc", "quality-reports", "team-performance", "board", date],
    queryFn: () => listQualityTeamPerformance(token, { grain: "day", date_from: date, date_to: date }),
  });
  const ncs = useQuery({ queryKey: ["qc", "non-conformities"], queryFn: () => listNonConformities(token) });

  if (conformity.isError || ncs.isError) {
    return (
      <BlockError
        onRetry={() => {
          void conformity.refetch();
          void ncs.refetch();
        }}
      />
    );
  }
  if (conformity.isLoading || ncs.isLoading || !conformity.data || !ncs.data) {
    return (
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    );
  }

  const good = conformity.data.reduce((sum, r) => sum + r.conforming_cartons, 0);
  const bad = conformity.data.reduce((sum, r) => sum + r.non_conforming_cartons, 0);
  const inspected = good + bad;
  const opened = ncs.data.filter((nc) => nc.raised_at?.startsWith(date)).length;
  const stillOpen = ncs.data.filter((nc) => nc.status !== "closed").length;

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {inspected > 0 ? (
        <Card icon={<InspectionIcon className="h-4 w-4" aria-hidden="true" />} label={t("production.board.quality.conformity")}>
          <div className="flex items-center gap-3">
            <svg width="76" height="76" viewBox="0 0 84 84" fill="none" aria-hidden="true">
              <circle cx="42" cy="42" r="34" stroke="#e5ebf2" strokeWidth="8" />
              <motion.circle cx="42" cy="42" r="34" stroke="#20A464" strokeWidth="8" strokeLinecap="round" strokeDasharray={RING_LENGTH} initial={{ strokeDashoffset: RING_LENGTH }} animate={{ strokeDashoffset: RING_LENGTH * (1 - good / inspected) }} transition={{ duration: 1.1 }} style={{ rotate: -90, transformOrigin: "50% 50%" }} />
            </svg>
            <div>
              <p className="text-2xl font-bold text-primary tabular-nums">{formatNumber((good / inspected) * 100, 1)}%</p>
              <p className="text-xs text-muted-foreground">
                {formatNumber(good, 0)} {t("production.board.quality.of")} {formatNumber(inspected, 0)}
              </p>
            </div>
          </div>
        </Card>
      ) : (
        <MissingState compact illustration={<QualityInspection className="h-16 w-auto" />} title={t("production.board.quality.empty.title")} description={t("production.board.quality.empty.desc")} />
      )}

      <Card icon={<NonconformityIcon className="h-4 w-4" aria-hidden="true" />} label={t("production.board.quality.nc")}>
        <p className="text-2xl font-bold text-primary tabular-nums">
          {opened} <span className="text-sm font-normal text-muted-foreground">{t("production.board.quality.ncOpened")}</span>
        </p>
        <p className="text-sm text-muted-foreground">
          {stillOpen} {t("production.board.quality.ncOpen")}
        </p>
      </Card>

      <Card icon={<ReleaseIcon className="h-4 w-4" aria-hidden="true" />} label={t("production.board.quality.lots.title")}>
        <p className="text-sm text-muted-foreground">{t("production.board.quality.lots.missing")}</p>
      </Card>
    </div>
  );
}
