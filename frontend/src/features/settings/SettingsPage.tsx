import { motion } from "framer-motion";
import { Clock, Globe, KeyRound, LogOut, Palette, ShieldCheck, UserCircle } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n, type Language } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { cn } from "../../lib/utils";
import { ExchangeRatesCard } from "./ExchangeRatesCard";

function formatDateTime(iso: string, language: Language) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const rowVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: (i: number) => ({ opacity: 1, y: 0, transition: { delay: i * 0.05, duration: 0.25 } }),
};

export function SettingsPage() {
  const { session, logout } = useAuth();
  const { t, language, setLanguage } = useI18n();

  const fields = [
    { icon: UserCircle, label: t("settings.account.userId"), value: session?.userId ?? "—" },
    { icon: ShieldCheck, label: t("settings.account.tenant"), value: session?.tenantId ?? "—" },
    {
      icon: Clock,
      label: t("settings.account.sessionExpires"),
      value: session ? formatDateTime(session.expiresAt, language) : "—",
    },
    {
      icon: KeyRound,
      label: t("settings.account.refreshExpires"),
      value: session ? formatDateTime(session.refreshExpiresAt, language) : "—",
    },
  ];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("settings.subtitle")}</p>
      </motion.div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("settings.account.title")}</CardTitle>
            <CardDescription>{t("settings.account.description")}</CardDescription>
          </div>
          <Badge variant="success" dot>
            {t("settings.account.active")}
          </Badge>
        </CardHeader>
        <CardContent className="divide-y divide-border p-0">
          {fields.map((field, i) => (
            <motion.div
              key={field.label}
              custom={i}
              variants={rowVariants}
              initial="hidden"
              animate="visible"
              className="flex items-center gap-3 px-5 py-3.5"
            >
              <field.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="w-48 shrink-0 text-sm text-muted-foreground">{field.label}</span>
              <span className="truncate text-sm font-medium">{field.value}</span>
            </motion.div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("settings.language.title")}</CardTitle>
            <CardDescription>{t("settings.language.description")}</CardDescription>
          </div>
          <Globe className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="inline-flex rounded-lg border border-border bg-muted/40 p-1">
            {(
              [
                { code: "en" as const, label: t("settings.language.en") },
                { code: "fr" as const, label: t("settings.language.fr") },
              ]
            ).map((option) => (
              <button
                key={option.code}
                onClick={() => setLanguage(option.code)}
                className={cn(
                  "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
                  language === option.code
                    ? "bg-background text-foreground shadow-soft"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <ExchangeRatesCard />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("settings.appearance.title")}</CardTitle>
            <CardDescription>{t("settings.appearance.description")}</CardDescription>
          </div>
          <Palette className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t("settings.appearance.note")}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("settings.session.title")}</CardTitle>
            <CardDescription>{t("settings.session.description")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={logout}>
            <LogOut className="h-4 w-4" />
            {t("settings.session.signOut")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
