import type { ReactNode } from "react";
import { useI18n } from "../../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import type { EmployeeRecord } from "../api";
import { END_REASON_LABEL, GENDER_LABEL, MARITAL_LABEL } from "../employeeLabels";
import { formatDate } from "../employeeFormat";
import { Masked } from "../Masked";

export function IdentityTab({ employee }: { employee: EmployeeRecord }) {
  const { t } = useI18n();
  const hidden = (value: string | null): ReactNode => (employee.sensitive_hidden ? <Masked /> : value);
  const sections: { title: string; rows: [string, ReactNode][] }[] = [
    {
      title: t("hr.form.section.identity"),
      rows: [
        [t("hr.field.employeeNo"), employee.employee_no],
        [t("hr.field.lastName"), employee.last_name],
        [t("hr.field.firstName"), employee.first_name],
        [t("hr.field.gender"), employee.gender ? t(GENDER_LABEL[employee.gender]) : null],
        [t("hr.field.birthDate"), employee.birth_date ? formatDate(employee.birth_date) : null],
        [t("hr.field.birthPlace"), employee.birth_place],
        [t("hr.field.nationality"), employee.nationality],
        [t("hr.field.maritalStatus"), employee.marital_status ? t(MARITAL_LABEL[employee.marital_status]) : null],
      ],
    },
    {
      title: t("hr.form.section.social"),
      rows: [
        [t("hr.field.nationalId"), hidden(employee.national_id)],
        [t("hr.field.inpsNo"), hidden(employee.inps_no)],
        [t("hr.field.amoNo"), hidden(employee.amo_no)],
      ],
    },
    {
      title: t("hr.form.section.contact"),
      rows: [
        [t("hr.field.phone"), employee.phone],
        [t("hr.field.email"), employee.email],
        [t("hr.field.address"), employee.address],
        [t("hr.field.emergencyContact"), employee.emergency_contact],
      ],
    },
    {
      title: t("hr.form.section.organisation"),
      rows: [
        [t("hr.field.department"), employee.department_name],
        [t("hr.field.position"), employee.position_title],
        [t("hr.field.grade"), employee.grade_code],
        [t("hr.field.jobTitle"), employee.job_title],
        [t("hr.field.site"), employee.site],
        [t("hr.field.badgeNo"), employee.badge_no],
        [t("hr.field.hireDate"), formatDate(employee.hire_date)],
        [t("hr.field.user"), employee.user_email],
      ],
    },
  ];
  if (employee.status === "terminated") {
    sections.push({
      title: t("hr.file.exit"),
      rows: [
        [t("hr.field.terminationDate"), formatDate(employee.termination_date)],
        [t("hr.field.terminationReason"), employee.termination_reason ? t(END_REASON_LABEL[employee.termination_reason]) : null],
      ],
    });
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {sections.map((section) => (
        <Card key={section.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{section.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-4 gap-y-2 text-sm">
              {section.rows.map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-medium">{value ?? "—"}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
