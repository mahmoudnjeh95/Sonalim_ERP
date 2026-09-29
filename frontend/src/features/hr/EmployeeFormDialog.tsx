import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Lock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { listUserDirectory, userDisplayName } from "../../lib/usersApi";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import {
  createEmployee,
  GENDERS,
  hrKeys,
  listDepartments,
  listGrades,
  listPositions,
  MARITAL_STATUSES,
  updateEmployee,
  type EmployeeChanges,
  type EmployeeInput,
  type EmployeeRecord,
} from "./api";
import { EMPLOYEE_STATUS_LABEL, GENDER_LABEL, MARITAL_LABEL } from "./employeeLabels";
import { emptyToNull, formatDate, todayIso } from "./employeeFormat";
import { FormField } from "./FormField";

const SENSITIVE_KEYS = ["national_id", "inps_no", "amo_no"] as const;
const EDITABLE_STATUSES = ["active", "on_leave", "inactive"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;

function buildSchema(required: string) {
  return z.object({
    employee_no: z.string().trim().min(1, required),
    first_name: z.string().trim().min(1, required),
    last_name: z.string().trim().min(1, required),
    hire_date: z.string().min(1, required),
    // Optional: the select is disabled for a person who left, and React Hook Form submits a
    // disabled field as undefined. Text inputs that must not be typed in use readOnly instead.
    status: z.enum(["active", "on_leave", "inactive", "terminated"]).optional(),
    gender: z.string(),
    birth_date: z.string(),
    birth_place: z.string(),
    nationality: z.string(),
    marital_status: z.string(),
    national_id: z.string(),
    inps_no: z.string(),
    amo_no: z.string(),
    phone: z.string(),
    email: z.string(),
    address: z.string(),
    emergency_contact: z.string(),
    department_id: z.string(),
    position_id: z.string(),
    grade_id: z.string(),
    job_title: z.string(),
    site: z.string(),
    badge_no: z.string(),
    user_id: z.string(),
  });
}
type EmployeeForm = z.infer<ReturnType<typeof buildSchema>>;
type FormKey = keyof EmployeeForm;

function toForm(employee: EmployeeRecord | null): EmployeeForm {
  const text = (value: string | null | undefined) => value ?? "";
  return {
    employee_no: text(employee?.employee_no),
    first_name: text(employee?.first_name),
    last_name: text(employee?.last_name),
    hire_date: employee?.hire_date ?? todayIso(),
    status: employee?.status ?? "active",
    gender: text(employee?.gender),
    birth_date: text(employee?.birth_date),
    birth_place: text(employee?.birth_place),
    nationality: text(employee?.nationality),
    marital_status: text(employee?.marital_status),
    national_id: text(employee?.national_id),
    inps_no: text(employee?.inps_no),
    amo_no: text(employee?.amo_no),
    phone: text(employee?.phone),
    email: text(employee?.email),
    address: text(employee?.address),
    emergency_contact: text(employee?.emergency_contact),
    department_id: text(employee?.department_id),
    position_id: text(employee?.position_id),
    grade_id: text(employee?.grade_id),
    job_title: text(employee?.job_title),
    site: text(employee?.site),
    badge_no: text(employee?.badge_no),
    user_id: text(employee?.user_id),
  };
}

/** The API body for `keys`: required text trimmed, everything else blank → null. */
function toPayload(values: EmployeeForm, keys: FormKey[]): Record<string, string | null> {
  const payload: Record<string, string | null> = {};
  for (const key of keys) {
    const raw = values[key] ?? "";
    payload[key] = key === "employee_no" || key === "first_name" || key === "last_name" ? raw.trim() : emptyToNull(raw);
  }
  return payload;
}

interface EmployeeFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null creates a new file. */
  employee: EmployeeRecord | null;
  onSaved?: (record: EmployeeRecord) => void;
}

export function EmployeeFormDialog({ open, onOpenChange, employee, onSaved }: EmployeeFormDialogProps) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canSeeSensitive = hasPermission("hr.view_sensitive");
  const schema = useMemo(() => buildSchema(t("common.required")), [t]);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, dirtyFields },
  } = useForm<EmployeeForm>({ resolver: zodResolver(schema), defaultValues: toForm(null) });

  useEffect(() => {
    if (open) reset(toForm(employee));
    // Reset on open and when another employee is shown, not when the same one is refetched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, employee?.id]);

  const departments = useQuery({ queryKey: hrKeys.departments, queryFn: () => listDepartments(token), enabled: open && hasPermission("hr.view_departments") });
  const positions = useQuery({ queryKey: hrKeys.positions, queryFn: () => listPositions(token), enabled: open && hasPermission("hr.view_positions") });
  const grades = useQuery({ queryKey: hrKeys.grades, queryFn: () => listGrades(token), enabled: open && hasPermission("hr.view_positions") });
  const users = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token), enabled: open });

  const mutation = useMutation({
    mutationFn: (values: EmployeeForm) => {
      if (!employee) {
        const keys = (Object.keys(values) as FormKey[]).filter(
          (key) => canSeeSensitive || !(SENSITIVE_KEYS as readonly string[]).includes(key),
        );
        return createEmployee(token, toPayload(values, keys) as unknown as EmployeeInput);
      }
      // Relinking user_id (not just leaving it as it is) needs hr.view_sensitive: once
      // self-service ships, whoever holds the login reads that file's hidden fields and
      // payslips through it. Follow the same "never send it" rule as the other sensitive keys.
      const keys = (Object.keys(dirtyFields) as FormKey[]).filter((key) => key !== "employee_no" && (canSeeSensitive || key !== "user_id"));
      return updateEmployee(token, employee.id, toPayload(values, keys) as unknown as EmployeeChanges);
    },
    onSuccess: (record) => {
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t(employee ? "hr.form.saved" : "hr.form.created"));
      onOpenChange(false);
      onSaved?.(record);
    },
    onError: (error) => toast.error(t("hr.form.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const terminated = employee?.status === "terminated";
  const sensitivePlaceholder = canSeeSensitive ? undefined : "••••";
  const sensitiveHint = canSeeSensitive ? undefined : t("hr.sensitive.readOnly");
  const sensitiveClass = canSeeSensitive ? undefined : "bg-muted";
  // Setting the link on create is open (nothing hidden exists yet); relinking an existing file
  // needs hr.view_sensitive, since self-service reads that file's hidden fields through it.
  const userLinkLocked = employee !== null && !canSeeSensitive;
  const grid = "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t(employee ? "hr.form.editTitle" : "hr.form.createTitle")}</DialogTitle>
          <DialogDescription>{t(employee ? "hr.form.editDescription" : "hr.form.createDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-5" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.form.section.identity")}</h3>
            <div className={grid}>
              <FormField id="employee_no" label={t("hr.field.employeeNo")} error={errors.employee_no?.message}>
                <Input id="employee_no" readOnly={employee !== null} className={employee ? "bg-muted" : undefined} {...register("employee_no")} />
              </FormField>
              <FormField id="last_name" label={t("hr.field.lastName")} error={errors.last_name?.message}>
                <Input id="last_name" {...register("last_name")} />
              </FormField>
              <FormField id="first_name" label={t("hr.field.firstName")} error={errors.first_name?.message}>
                <Input id="first_name" {...register("first_name")} />
              </FormField>
              <FormField id="gender" label={t("hr.field.gender")}>
                <Select id="gender" {...register("gender")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {GENDERS.map((value) => (
                    <option key={value} value={value}>
                      {t(GENDER_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="birth_date" label={t("hr.field.birthDate")}>
                <Input id="birth_date" type="date" {...register("birth_date")} />
              </FormField>
              <FormField id="birth_place" label={t("hr.field.birthPlace")}>
                <Input id="birth_place" {...register("birth_place")} />
              </FormField>
              <FormField id="nationality" label={t("hr.field.nationality")}>
                <Input id="nationality" {...register("nationality")} />
              </FormField>
              <FormField id="marital_status" label={t("hr.field.maritalStatus")}>
                <Select id="marital_status" {...register("marital_status")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {MARITAL_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {t(MARITAL_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              {t("hr.form.section.social")}
              {!canSeeSensitive && <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label={t("hr.sensitive.hidden")} />}
            </h3>
            <div className={grid}>
              <FormField id="national_id" label={t("hr.field.nationalId")} hint={sensitiveHint}>
                <Input id="national_id" readOnly={!canSeeSensitive} className={sensitiveClass} placeholder={sensitivePlaceholder} {...register("national_id")} />
              </FormField>
              <FormField id="inps_no" label={t("hr.field.inpsNo")}>
                <Input id="inps_no" readOnly={!canSeeSensitive} className={sensitiveClass} placeholder={sensitivePlaceholder} {...register("inps_no")} />
              </FormField>
              <FormField id="amo_no" label={t("hr.field.amoNo")}>
                <Input id="amo_no" readOnly={!canSeeSensitive} className={sensitiveClass} placeholder={sensitivePlaceholder} {...register("amo_no")} />
              </FormField>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.form.section.contact")}</h3>
            <div className={grid}>
              <FormField id="phone" label={t("hr.field.phone")}>
                <Input id="phone" {...register("phone")} />
              </FormField>
              <FormField id="email" label={t("hr.field.email")}>
                <Input id="email" type="email" {...register("email")} />
              </FormField>
              <FormField id="address" label={t("hr.field.address")}>
                <Input id="address" {...register("address")} />
              </FormField>
              <FormField id="emergency_contact" label={t("hr.field.emergencyContact")}>
                <Input id="emergency_contact" {...register("emergency_contact")} />
              </FormField>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.form.section.organisation")}</h3>
            <div className={grid}>
              <FormField id="hire_date" label={t("hr.field.hireDate")} error={errors.hire_date?.message}>
                <Input id="hire_date" type="date" {...register("hire_date")} />
              </FormField>
              <FormField id="status" label={t("hr.field.status")} hint={terminated ? t("hr.form.terminatedStatus") : undefined}>
                <Select id="status" disabled={terminated} {...register("status")}>
                  {(terminated ? (["terminated"] as const) : EDITABLE_STATUSES).map((value) => (
                    <option key={value} value={value}>
                      {t(EMPLOYEE_STATUS_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="department_id" label={t("hr.field.department")}>
                <Select id="department_id" {...register("department_id")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {(departments.data ?? []).map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="position_id" label={t("hr.field.position")}>
                <Select id="position_id" {...register("position_id")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {(positions.data ?? []).map((position) => (
                    <option key={position.id} value={position.id}>
                      {position.code} — {position.title}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="grade_id" label={t("hr.field.grade")}>
                <Select id="grade_id" {...register("grade_id")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {(grades.data ?? []).map((grade) => (
                    <option key={grade.id} value={grade.id}>
                      {grade.code} — {grade.category} {grade.echelon} ({formatDate(grade.valid_from)})
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="job_title" label={t("hr.field.jobTitle")}>
                <Input id="job_title" {...register("job_title")} />
              </FormField>
              <FormField id="site" label={t("hr.field.site")}>
                <Input id="site" {...register("site")} />
              </FormField>
              <FormField id="badge_no" label={t("hr.field.badgeNo")}>
                <Input id="badge_no" {...register("badge_no")} />
              </FormField>
              <FormField id="user_id" label={t("hr.field.user")} hint={userLinkLocked ? t("hr.sensitive.readOnly") : undefined}>
                <Select id="user_id" disabled={userLinkLocked} className={userLinkLocked ? "bg-muted" : undefined} {...register("user_id")}>
                  <option value="">{t("hr.form.noUser")}</option>
                  {(users.data ?? []).map((user) => (
                    <option key={user.id} value={user.id}>
                      {userDisplayName(user)}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </section>

          <Button
            type="submit"
            className="w-full"
            disabled={mutation.isPending || (employee !== null && Object.keys(dirtyFields).length === 0)}
          >
            {mutation.isPending ? t("common.saving") : t(employee ? "hr.form.save" : "hr.form.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
