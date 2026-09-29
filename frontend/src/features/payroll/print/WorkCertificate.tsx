import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { hrKeys, listPositions } from "../../hr/api";
import { CONTRACT_TYPE_LABEL, END_REASON_LABEL } from "../../hr/employeeLabels";
import type { WorkCertificateData } from "../api";
import { formatDay } from "./PrintShell";

/**
 * The work certificate printed with a final-settlement payslip. The backend gives the position as an
 * id only: its title is looked up for readers of HR positions, and the line is left out otherwise
 * rather than printing an opaque id on a certificate.
 */
export function WorkCertificate({ certificate }: { certificate: WorkCertificateData }) {
  const { t, language } = useI18n();
  const { session, hasPermission } = useAuth();
  const locale = language === "fr" ? "fr-FR" : "en-US";
  const canReadPositions = !!certificate.position_id && hasPermission("hr.view_positions");
  const { data: positions } = useQuery({
    queryKey: hrKeys.positions,
    queryFn: () => listPositions(session?.token ?? ""),
    enabled: canReadPositions,
  });
  const position = positions?.find((entry) => entry.id === certificate.position_id)?.title ?? null;

  const label = (map: Record<string, TranslationKey>, value: string | null) => (value ? (map[value] ? t(map[value]) : value) : null);
  const contractType = label(CONTRACT_TYPE_LABEL, certificate.contract_type);
  const reason = label(END_REASON_LABEL, certificate.termination_reason);

  // t() has no interpolation: the dynamic fragments are swapped in here.
  const body = t("payroll.print.certificate.body")
    .replace("{name}", certificate.full_name)
    .replace("{employeeNo}", certificate.employee_no)
    .replace("{company}", certificate.company.name ?? t("payroll.print.certificate.theCompany"))
    .replace("{hireDate}", formatDay(certificate.hire_date, locale))
    .replace("{terminationDate}", formatDay(certificate.termination_date, locale));

  const details = [
    { label: t("payroll.print.certificate.position"), value: position },
    { label: t("payroll.print.certificate.contractType"), value: contractType },
    { label: t("payroll.print.certificate.reason"), value: reason },
  ].filter((row): row is { label: string; value: string } => !!row.value);

  return (
    <div className="space-y-5 text-sm break-inside-avoid">
      <h2 className="text-center text-lg font-semibold uppercase tracking-wide">{t("payroll.print.certificate.title")}</h2>
      <p className="leading-relaxed">{body}</p>
      {details.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {details.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-neutral-600">{row.label}</dt>
              <dd className="font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="leading-relaxed">{t("payroll.print.certificate.closing")}</p>
      <div className="flex justify-end pt-4">
        <div className="w-64 space-y-10 text-right text-xs">
          <p>{t("payroll.print.certificate.issuedOn").replace("{date}", formatDay(certificate.issued_on, locale))}</p>
          <p className="border-t border-neutral-900 pt-1 text-center print:border-black">{t("payroll.print.certificate.signature")}</p>
        </div>
      </div>
    </div>
  );
}
