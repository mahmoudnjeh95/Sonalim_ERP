import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { Camera, Trash2 } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n, type Language } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { AppLoader } from "../../components/patterns/AppLoader";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { UserAvatar } from "./UserAvatar";
import { prepareAvatar } from "./avatarImage";
import { useMyAvatar, useMyProfile, useRemoveMyAvatar, useSetMyAvatar, type MyProfile } from "./api";

function formatDate(iso: string | null, language: Language): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium" });
}

/** One read-only field of the employee file. HR owns these values; this page only shows them. */
function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="px-4 py-3 sm:px-5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-0.5 break-words text-sm">{value || "—"}</p>
    </div>
  );
}

function EmployeeFileCard({ profile }: { profile: MyProfile }) {
  const { t, language } = useI18n();

  const maritalStatusLabel = (status: string | null): string | null => {
    if (status === "single") return t("profile.maritalStatus.single");
    if (status === "married") return t("profile.maritalStatus.married");
    if (status === "divorced") return t("profile.maritalStatus.divorced");
    if (status === "widowed") return t("profile.maritalStatus.widowed");
    return null;
  };

  const sections = [
    {
      title: t("profile.sections.identity"),
      fields: [
        { label: t("profile.fields.employeeNo"), value: profile.employee_no },
        { label: t("profile.fields.fullName"), value: profile.full_name },
        { label: t("profile.fields.birthDate"), value: formatDate(profile.birth_date, language) },
        { label: t("profile.fields.birthPlace"), value: profile.birth_place },
        { label: t("profile.fields.nationality"), value: profile.nationality },
        { label: t("profile.fields.maritalStatus"), value: maritalStatusLabel(profile.marital_status) },
      ],
    },
    {
      title: t("profile.sections.job"),
      fields: [
        { label: t("profile.fields.jobTitle"), value: profile.job_title ?? profile.position_title },
        { label: t("profile.fields.department"), value: profile.department_name },
        { label: t("profile.fields.grade"), value: profile.grade_code },
        { label: t("profile.fields.hireDate"), value: formatDate(profile.hire_date, language) },
        { label: t("profile.fields.site"), value: profile.site },
        { label: t("profile.fields.badgeNo"), value: profile.badge_no },
      ],
    },
    {
      title: t("profile.sections.contact"),
      fields: [
        { label: t("profile.fields.address"), value: profile.address },
        { label: t("profile.fields.emergencyContact"), value: profile.emergency_contact },
        { label: t("profile.fields.nationalId"), value: profile.national_id },
        { label: t("profile.fields.inpsNo"), value: profile.inps_no },
        { label: t("profile.fields.amoNo"), value: profile.amo_no },
      ],
    },
  ];

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("profile.file.title")}</CardTitle>
          <CardDescription>{t("profile.file.description")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 p-0 pb-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="px-4 pb-1.5 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70 sm:px-5">
              {section.title}
            </p>
            <div className="grid grid-cols-1 border-t border-border sm:grid-cols-2">
              {section.fields.map((field) => (
                <div key={field.label} className="border-b border-border">
                  <Field label={field.label} value={field.value} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function PhotoCard({ name }: { name: string | null }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data: blob } = useMyAvatar();
  const setAvatar = useSetMyAvatar();
  const removeAvatar = useRemoveMyAvatar();
  const fileInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const choose = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      setAvatar.mutate(await prepareAvatar(file), {
        onError: (failure) => setError(failure instanceof ApiError ? failure.message : t("profile.photo.failed")),
      });
    } catch {
      // createImageBitmap rejects on a file that is not a decodable image
      setError(t("profile.photo.notAnImage"));
    }
  };

  const busy = setAvatar.isPending || removeAvatar.isPending;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("profile.photo.title")}</CardTitle>
          <CardDescription>{t("profile.photo.description")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-4 pb-6 text-center">
        <UserAvatar name={name} email={session?.email} className="h-24 w-24 text-3xl" />
        <div className="flex flex-wrap justify-center gap-2">
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => fileInput.current?.click()}>
            <Camera className="mr-1.5 h-4 w-4" />
            {blob ? t("profile.photo.change") : t("profile.photo.add")}
          </Button>
          {blob && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                setError(null);
                removeAvatar.mutate(undefined, {
                  onError: (failure) => setError(failure instanceof ApiError ? failure.message : t("profile.photo.failed")),
                });
              }}
            >
              <Trash2 className="mr-1.5 h-4 w-4" />
              {t("profile.photo.remove")}
            </Button>
          )}
        </div>
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(event) => {
            void choose(event.target.files?.[0]);
            event.target.value = ""; // so picking the same file again still fires
          }}
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <p className="text-xs text-muted-foreground">{t("profile.photo.hint")}</p>
      </CardContent>
    </Card>
  );
}

export function ProfilePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const profile = useMyProfile();

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("profile.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("profile.subtitle")}</p>
      </motion.div>

      {profile.isLoading ? (
        <AppLoader label={t("profile.loading")} />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="space-y-6">
            <PhotoCard name={profile.data?.full_name ?? null} />
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("profile.account.title")}</CardTitle>
                  <CardDescription>{t("profile.account.description")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="divide-y divide-border p-0 pb-1">
                <Field label={t("profile.account.email")} value={session?.email} />
                <Field label={t("profile.account.tenant")} value={session?.tenantId} />
              </CardContent>
            </Card>
          </div>

          {profile.data ? (
            <EmployeeFileCard profile={profile.data} />
          ) : (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("profile.file.title")}</CardTitle>
                  <CardDescription>{t("profile.file.description")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pb-6">
                <p className="text-sm text-muted-foreground">{t("profile.file.none")}</p>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
