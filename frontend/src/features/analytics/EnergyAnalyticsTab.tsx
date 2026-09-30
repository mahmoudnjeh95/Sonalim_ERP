import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../components/charts/InteractiveChart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { listWorkCenters } from "../production/api";
import { formatNumber } from "./manufacturing/format";
import { useEnergyAnalytics } from "./manufacturing/useEnergyAnalytics";
import { useMinimumLoading } from "./useMinimumLoading";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import ProductionLineIllustration from "../../assets/illustrations/production-line.svg?react";

const FUEL_COLOR = "hsl(38 92% 42%)";
const GASOIL_COLOR = "hsl(217 91% 45%)";
const ELECTRICITY_COLOR = "hsl(152 69% 31%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };

function PerTonne({ value, previous, unit, label }: { value: number | null; previous: number | null; unit: string; label: string }) {
  const { t } = useI18n();
  return (
    <div>
      <p className="text-2xl font-semibold tabular-nums">{value === null ? "—" : `${formatNumber(value, 2)} ${unit}`}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xs text-muted-foreground">
        {t("analytics.kpi.previous")}: {previous === null ? "—" : `${formatNumber(previous, 2)} ${unit}`}
      </p>
    </div>
  );
}

/** Energy as the shifts recorded it: fioul and gasoil in litres, electricity in kWh, the
 * generator in hours -- kept apart, never summed across units. */
export function EnergyAnalyticsTab() {
  const { t } = useI18n();
  const { session } = useAuth();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, energyCurrent, summary, previousSummary } = useEnergyAnalytics(days);
  const showLoader = useMinimumLoading(energyCurrent.isLoading);
  const workCenters = useQuery({ queryKey: ["analytics", "work-centers"], queryFn: () => listWorkCenters(session!.token) });
  const lineName = new Map((workCenters.data ?? []).map((w) => [w.id, w.name]));

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (energyCurrent.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => energyCurrent.refetch()} />
        </Card>
      </div>
    );
  }
  if ((energyCurrent.data ?? []).length === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={ProductionLineIllustration} title={t("analytics.energy.empty.title")} description={t("analytics.energy.empty.description")} />
        </Card>
      </div>
    );
  }

  const byLine = summary.byLine.map((l) => ({ line: lineName.get(l.workCenterId) ?? l.workCenterId, gasoil: l.gasoilPerTonne }));

  return (
    <div className="space-y-5">
      {header}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("analytics.energy.trend.title")}</CardTitle>
            <CardDescription>{t("analytics.energy.trend.subtitle")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="h-64 w-full">
            <InteractiveChart height="100%">
              <LineChart data={summary.byDate} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="date" tick={TICK} tickLine={false} axisLine={false} minTickGap={32} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} width={48} unit=" l" />
                <Tooltip formatter={(value) => `${formatNumber(Number(value), 1)} l`} />
                <Legend />
                <Line type="linear" dataKey="fuel" name={t("analytics.energy.fuel")} stroke={FUEL_COLOR} strokeWidth={2} dot={summary.byDate.length < 3} />
                <Line type="linear" dataKey="gasoil" name={t("analytics.energy.gasoil")} stroke={GASOIL_COLOR} strokeWidth={2} dot={summary.byDate.length < 3} />
              </LineChart>
            </InteractiveChart>
          </div>
          <div className="h-64 w-full">
            <InteractiveChart height="100%">
              <LineChart data={summary.byDate} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="date" tick={TICK} tickLine={false} axisLine={false} minTickGap={32} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} width={56} unit=" kWh" />
                <Tooltip formatter={(value) => `${formatNumber(Number(value), 0)} kWh`} />
                <Legend />
                <Line
                  type="linear"
                  dataKey="electricity"
                  name={t("analytics.energy.electricity")}
                  stroke={ELECTRICITY_COLOR}
                  strokeWidth={2}
                  dot={summary.byDate.length < 3}
                />
              </LineChart>
            </InteractiveChart>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.energy.perTonne.title")}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-3 text-center">
            <PerTonne value={summary.fuelPerTonne} previous={previousSummary.fuelPerTonne} unit="l/t" label={t("analytics.energy.fuel")} />
            <PerTonne value={summary.gasoilPerTonne} previous={previousSummary.gasoilPerTonne} unit="l/t" label={t("analytics.energy.gasoil")} />
            <PerTonne
              value={summary.electricityPerTonne}
              previous={previousSummary.electricityPerTonne}
              unit="kWh/t"
              label={t("analytics.energy.electricity")}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.energy.generator.title")}</CardTitle>
            <CardDescription>{t("analytics.energy.generator.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">{formatNumber(summary.totals.generatorHours, 1)} h</p>
            <p className="text-xs text-muted-foreground">
              {t("analytics.kpi.previous")}: {formatNumber(previousSummary.totals.generatorHours, 1)} h
            </p>
          </CardContent>
        </Card>
      </div>

      {byLine.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.energy.byLine.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              <InteractiveChart height="100%">
                <BarChart data={byLine} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="line" tick={TICK} tickLine={false} axisLine={false} />
                  <YAxis tick={TICK} tickLine={false} axisLine={false} width={48} unit=" l/t" />
                  <Tooltip formatter={(value) => `${formatNumber(Number(value), 2)} l/t`} />
                  <Bar dataKey="gasoil" name={t("analytics.energy.gasoil")} fill={GASOIL_COLOR} radius={[4, 4, 0, 0]} />
                </BarChart>
              </InteractiveChart>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
