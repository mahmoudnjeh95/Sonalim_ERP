import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { getExpiryAlerts, hrKeys, type ContractAlert, type DocumentAlert } from "./api";
import { CONTRACT_TYPE_LABEL, DOCUMENT_KIND_LABEL, DOCUMENT_STATE_LABEL, DOCUMENT_STATE_VARIANT } from "./employeeLabels";
import { formatDate } from "./employeeFormat";

/** Contracts, trial periods and documents falling due inside the horizons HR set (Organisation › Settings). */
export function ExpiryAlertsCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data, isLoading, isError } = useQuery({ queryKey: hrKeys.alerts, queryFn: () => getExpiryAlerts(session!.token) });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="h-4 w-4 text-primary" />
          {t("hr.alerts.title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="grid gap-4 md:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-24 w-full" />
            ))}
          </div>
        )}
        {isError && <p className="text-sm text-destructive">{t("hr.alerts.error")}</p>}
        {data && (
          <div className="grid gap-4 md:grid-cols-3">
            <AlertColumn title={t("hr.alerts.contracts")} days={data.contract_expiry_horizon_days} empty={data.contracts_ending.length === 0}>
              {data.contracts_ending.map((item) => (
                <ContractLine key={item.contract_id} item={item} />
              ))}
            </AlertColumn>
            <AlertColumn title={t("hr.alerts.trials")} days={data.trial_end_horizon_days} empty={data.trials_ending.length === 0}>
              {data.trials_ending.map((item) => (
                <ContractLine key={item.contract_id} item={item} />
              ))}
            </AlertColumn>
            <AlertColumn title={t("hr.alerts.documents")} days={data.document_expiry_horizon_days} empty={data.documents_expiring.length === 0}>
              {data.documents_expiring.map((item) => (
                <DocumentLine key={item.document_id} item={item} />
              ))}
            </AlertColumn>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AlertColumn({ title, days, empty, children }: { title: string; days: number | null; empty: boolean; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{title}</p>
        {days !== null && (
          <span className="text-xs text-muted-foreground">
            {days} {t("hr.alerts.withinDays")}
          </span>
        )}
      </div>
      {days === null ? (
        <p className="text-xs text-muted-foreground">{t("hr.alerts.notConfigured")}</p>
      ) : empty ? (
        <p className="text-xs text-muted-foreground">{t("hr.alerts.none")}</p>
      ) : (
        <ul className="space-y-1">{children}</ul>
      )}
    </div>
  );
}

function ContractLine({ item }: { item: ContractAlert }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <Link to={`/hr/employees/${item.employee_id}?tab=contracts`} className="truncate hover:underline">
        {item.employee_name}
      </Link>
      <span className="shrink-0 text-xs text-muted-foreground">
        {t(CONTRACT_TYPE_LABEL[item.contract_type])} · {formatDate(item.date)}
      </span>
    </li>
  );
}

function DocumentLine({ item }: { item: DocumentAlert }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <Link to={`/hr/employees/${item.employee_id}?tab=documents`} className="truncate hover:underline">
        {item.employee_name} · {item.title ?? t(DOCUMENT_KIND_LABEL[item.kind])}
      </Link>
      <Badge variant={DOCUMENT_STATE_VARIANT[item.state]}>
        {t(DOCUMENT_STATE_LABEL[item.state])} · {formatDate(item.expires_on)}
      </Badge>
    </li>
  );
}
