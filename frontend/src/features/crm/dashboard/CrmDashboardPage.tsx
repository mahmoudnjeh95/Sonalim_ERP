import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  ClipboardCheck,
  Coins,
  MessageSquare,
  Percent,
  Phone,
  PieChart as PieChartIcon,
  Target,
  Trophy,
  CheckSquare,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n, type Language } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { Skeleton } from "../../../components/ui/skeleton";
import { StatCard } from "../../../components/patterns/StatCard";
import { HelpTooltip } from "../../../components/patterns/HelpTooltip";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StatusBadge } from "../../../components/patterns/StatusBadge";
import { getCrmDashboard, type RecentActivity } from "./api";

const CHART_COLORS = {
  primary: "hsl(217 91% 45%)",
  primarySoft: "hsl(217 91% 88%)",
  accent: "hsl(258 90% 66%)",
  success: "hsl(152 69% 31%)",
  warning: "hsl(38 92% 42%)",
  destructive: "hsl(0 72% 51%)",
  muted: "hsl(215 16% 70%)",
};

const STAGE_COLORS: Record<string, string> = {
  prospecting: CHART_COLORS.muted,
  qualification: CHART_COLORS.primary,
  proposal: CHART_COLORS.accent,
  negotiation: CHART_COLORS.warning,
  won: CHART_COLORS.success,
  lost: CHART_COLORS.destructive,
};

const KIND_COLORS: Record<string, string> = {
  comment: CHART_COLORS.primarySoft,
  task: CHART_COLORS.warning,
  call: CHART_COLORS.success,
};

const KIND_ICON: Record<string, typeof MessageSquare> = {
  comment: MessageSquare,
  task: CheckSquare,
  call: Phone,
};

const MONTH_LABELS = {
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  fr: ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"],
};

function relativeTime(iso: string, language: Language) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMinutes = Math.round(diffMs / 60000);
  const rtf = new Intl.RelativeTimeFormat(language === "fr" ? "fr-FR" : "en-US", { numeric: "auto" });
  if (Math.abs(diffMinutes) < 60) return rtf.format(-diffMinutes, "minute");
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) return rtf.format(-diffHours, "hour");
  const diffDays = Math.round(diffHours / 24);
  return rtf.format(-diffDays, "day");
}

const DASHBOARD_QUERY_KEY = ["crm", "dashboard"] as const;

function formatMoney(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

export function CrmDashboardPage() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;

  const { data, isLoading, isError } = useQuery({
    queryKey: DASHBOARD_QUERY_KEY,
    queryFn: () => getCrmDashboard(token),
  });

  const months = MONTH_LABELS[language];
  const monthlyData = data
    ? months.map((label, i) => ({
        month: label,
        [String(data.opportunities_by_month.previous_year)]: data.opportunities_by_month.previous[i],
        [String(data.opportunities_by_month.current_year)]: data.opportunities_by_month.current[i],
      }))
    : [];

  const pipelineData = data
    ? Object.entries(data.pipeline_by_stage)
        .filter(([stage]) => stage !== "won" && stage !== "lost")
        .map(([stage, bucket]) => ({ stage, count: bucket.count, amount: bucket.amount }))
    : [];

  const activityMixData = data
    ? Object.entries(data.activities_by_kind).map(([kind, count]) => ({ kind, count }))
    : [];

  const leadsTotal = data ? Object.values(data.leads_by_status).reduce((sum, n) => sum + n, 0) : 0;
  const partnersTotal = data ? Object.values(data.partners_by_status).reduce((sum, n) => sum + n, 0) : 0;

  // Win rate and average deal size come from the same pipeline_by_stage bucket
  // the funnel chart already fetches — no extra request, just numbers the funnel
  // was discarding (it filters won/lost out to draw the open-stage funnel).
  const wonBucket = data?.pipeline_by_stage.won;
  const lostBucket = data?.pipeline_by_stage.lost;
  const decidedCount = (wonBucket?.count ?? 0) + (lostBucket?.count ?? 0);
  const winRate = decidedCount > 0 ? (100 * (wonBucket?.count ?? 0)) / decidedCount : null;
  const avgDealSize = wonBucket && wonBucket.count > 0 ? wonBucket.amount / wonBucket.count : null;

  // Snapshot totals (forecast, won) tell you where things stand; these tell you
  // what to do next. Keeping them apart means a scan of the page answers "am I
  // okay?" before it answers "how did I get here?".
  const attentionRows = [
    ...(data && data.overdue.count > 0
      ? [
          {
            code: "overdue",
            tone: "destructive" as const,
            title: t("crm.dashboard.attention.overdue"),
            detail: `${data.overdue.count} · $${formatMoney(data.overdue.amount)}`,
          },
        ]
      : []),
    ...(data && data.due_this_week.count > 0
      ? [
          {
            code: "due-this-week",
            tone: "warning" as const,
            title: t("crm.dashboard.attention.dueThisWeek"),
            detail: `${data.due_this_week.count} · $${formatMoney(data.due_this_week.amount)}`,
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("crm.dashboard.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("crm.dashboard.subtitle")}</p>
      </motion.div>

      {isError && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-destructive">{t("crm.dashboard.loadError")}</CardContent>
        </Card>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {t("crm.dashboard.help.forecastLabel")}
            <HelpTooltip text={t("crm.dashboard.help.forecast")} />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard
              label={t("crm.dashboard.stat.forecast")}
              value={Math.round(data.forecast.amount)}
              icon={<Target className="h-5 w-5" />}
              accent="primary"
              prefix="$"
            />
            <StatCard
              label={t("crm.dashboard.stat.forecastWeighted")}
              value={Math.round(data.forecast_weighted.amount)}
              icon={<Target className="h-5 w-5" />}
              accent="primary"
              prefix="$"
            />
            <StatCard
              label={t("crm.dashboard.stat.won")}
              value={Math.round(data.won_amount)}
              icon={<Trophy className="h-5 w-5" />}
              accent="success"
              prefix="$"
            />
            <StatCard
              label={t("crm.dashboard.stat.winRate")}
              value={winRate ?? 0}
              unit="%"
              decimals={1}
              icon={<Percent className="h-5 w-5" />}
              accent="accent"
            />
            <StatCard
              label={t("crm.dashboard.stat.avgDealSize")}
              value={Math.round(avgDealSize ?? 0)}
              icon={<Coins className="h-5 w-5" />}
              accent="accent"
              prefix="$"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t("crm.dashboard.attention.title")}</CardTitle>
            </CardHeader>
            <CardContent className={attentionRows.length === 0 ? "p-0" : "space-y-2"}>
              {attentionRows.length === 0 ? (
                <EmptyState
                  icon={<ClipboardCheck className="h-5 w-5" />}
                  title={t("crm.dashboard.attention.empty.title")}
                  description={t("crm.dashboard.attention.empty.description")}
                />
              ) : (
                attentionRows.map((row) => (
                  <Link
                    key={row.code}
                    to="/crm/opportunities"
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                      row.tone === "destructive"
                        ? "border-destructive/20 bg-destructive-soft hover:bg-destructive-soft/70"
                        : "border-warning/20 bg-warning-soft hover:bg-warning-soft/70",
                    )}
                  >
                    {row.code === "overdue" ? (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                    ) : (
                      <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                    )}
                    <div className="min-w-0">
                      <p className={cn("text-sm font-medium", row.tone === "destructive" ? "text-destructive" : "text-warning")}>{row.title}</p>
                      <p className="text-sm text-muted-foreground">{row.detail}</p>
                    </div>
                    <span className="ml-auto self-center text-xs text-muted-foreground">{t("crm.dashboard.attention.open")}</span>
                  </Link>
                ))
              )}
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <div>
                  <CardTitle>{t("crm.dashboard.chart.opportunities.title")}</CardTitle>
                  <CardDescription>{t("crm.dashboard.chart.opportunities.description")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                    <XAxis dataKey="month" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{
                        borderRadius: 10,
                        border: "1px solid hsl(214 20% 88%)",
                        fontSize: 13,
                        fontFamily: "Inter, sans-serif",
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar
                      dataKey={String(data.opportunities_by_month.previous_year)}
                      fill={CHART_COLORS.primarySoft}
                      radius={[4, 4, 0, 0]}
                    />
                    <Bar
                      dataKey={String(data.opportunities_by_month.current_year)}
                      fill={CHART_COLORS.primary}
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("crm.dashboard.chart.pipeline.title")}</CardTitle>
                </div>
                <PieChartIcon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                {pipelineData.length === 0 || pipelineData.every((d) => d.count === 0) ? (
                  <EmptyState
                    icon={<Target className="h-5 w-5" />}
                    title={t("crm.dashboard.chart.pipeline.empty")}
                    description=""
                  />
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={200}>
                      <PieChart>
                        <Pie data={pipelineData} dataKey="count" nameKey="stage" innerRadius={50} outerRadius={80} paddingAngle={2}>
                          {pipelineData.map((entry) => (
                            <Cell key={entry.stage} fill={STAGE_COLORS[entry.stage] ?? CHART_COLORS.muted} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13 }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
                      {pipelineData.map((entry) => (
                        <div key={entry.stage} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{ backgroundColor: STAGE_COLORS[entry.stage] ?? CHART_COLORS.muted }}
                          />
                          <StatusBadge status={entry.stage} />
                          <span className="tabular-nums">{entry.count}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <div>
                  <CardTitle>{t("crm.dashboard.activity.title")}</CardTitle>
                  <CardDescription>{t("crm.dashboard.activity.description")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {data.recent_activities.length === 0 ? (
                  <EmptyState
                    icon={<MessageSquare className="h-5 w-5" />}
                    title={t("crm.dashboard.activity.empty.title")}
                    description={t("crm.dashboard.activity.empty.description")}
                  />
                ) : (
                  <ul className="scrollbar-thin max-h-72 space-y-1 overflow-y-auto">
                    {data.recent_activities.map((activity, i) => (
                      <ActivityRow key={activity.id} activity={activity} index={i} language={language} />
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <div>
                    <CardTitle>{t("crm.dashboard.activityMix.title")}</CardTitle>
                    <CardDescription>{t("crm.dashboard.activityMix.subtitle")}</CardDescription>
                  </div>
                </CardHeader>
                <CardContent>
                  {activityMixData.length === 0 ? (
                    <p className="py-6 text-center text-sm text-muted-foreground">{t("crm.dashboard.activityMix.empty")}</p>
                  ) : (
                    <ResponsiveContainer width="100%" height={140}>
                      <PieChart>
                        <Pie data={activityMixData} dataKey="count" nameKey="kind" innerRadius={30} outerRadius={55} paddingAngle={2}>
                          {activityMixData.map((entry) => (
                            <Cell key={entry.kind} fill={KIND_COLORS[entry.kind] ?? CHART_COLORS.muted} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13 }} />
                        <Legend
                          wrapperStyle={{ fontSize: 11 }}
                          formatter={(value: string) => t(`crm.activity.kind.${value}` as Parameters<typeof t>[0])}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>{t("crm.dashboard.snapshot.title")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{t("crm.dashboard.snapshot.leads")}</span>
                    <span className="font-semibold tabular-nums">{leadsTotal}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{t("crm.dashboard.snapshot.accounts")}</span>
                    <span className="font-semibold tabular-nums">{partnersTotal}</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ActivityRow({ activity, index, language }: { activity: RecentActivity; index: number; language: Language }) {
  const { t } = useI18n();
  const Icon = KIND_ICON[activity.kind] ?? MessageSquare;
  return (
    <motion.li
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0, transition: { delay: Math.min(index * 0.03, 0.2) } }}
      className="flex items-start gap-3 rounded-lg px-2 py-2.5 hover:bg-muted/50"
    >
      <div
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
        style={{ backgroundColor: `${KIND_COLORS[activity.kind] ?? CHART_COLORS.muted}22`, color: KIND_COLORS[activity.kind] ?? CHART_COLORS.muted }}
      >
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{activity.note}</p>
        <p className="text-xs text-muted-foreground">
          {t(`crm.activity.subject.${activity.subject_type}` as Parameters<typeof t>[0])} · {relativeTime(activity.created_at, language)}
        </p>
      </div>
    </motion.li>
  );
}
