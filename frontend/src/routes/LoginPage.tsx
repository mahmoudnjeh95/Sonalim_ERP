import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import { Eye, EyeOff, Loader2, Lock, Mail } from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { ApiError } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { BrandWordmark } from "../components/patterns/BrandLoader";
import { LanguageToggle } from "../components/patterns/LanguageToggle";
import LogoMark from "../assets/animations/logo-mark.svg?react";

const FEATURES: TranslationKey[] = ["login.feature.production", "login.feature.quality", "login.feature.warehouse"];

const EASE = [0.22, 1, 0.36, 1] as const;

/** Entrance for the form column: each child arrives a beat after the previous one. */
const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.2 } },
};
const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

const fieldClass =
  "h-11 rounded-xl border-slate-200 bg-slate-50/80 pl-10 text-slate-900 shadow-sm transition-all duration-200 placeholder:text-slate-400 focus:border-[#F5A900] focus:bg-white focus-visible:ring-4 focus-visible:ring-[#F5A900]/15";

export function LoginPage() {
  const { login } = useAuth();
  const { t, language, setLanguage } = useI18n();
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(email, password);
      navigate("/crm", { replace: true });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("login.failed"));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="theme-login relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-8">
      <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
        <motion.div
          className="absolute -left-16 top-16 h-72 w-72 rounded-full bg-primary/10 blur-3xl"
          animate={reduceMotion ? undefined : { x: [0, 30, 0], y: [0, -20, 0], scale: [1, 1.1, 1] }}
          transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute -right-20 bottom-10 h-80 w-80 rounded-full bg-accent/10 blur-3xl"
          animate={reduceMotion ? undefined : { x: [0, -25, 0], y: [0, 18, 0], scale: [1, 1.15, 1] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute left-1/2 top-1/2 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary/10"
          animate={reduceMotion ? undefined : { rotate: 360 }}
          transition={{ duration: 28, repeat: Infinity, ease: "linear" }}
        />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: EASE }}
        className="relative z-10 w-full max-w-5xl overflow-hidden rounded-[32px] border border-white/40 bg-white/75 shadow-[0_35px_90px_rgba(7,31,67,0.18)] backdrop-blur-xl"
      >
        <div className="grid md:grid-cols-[1.1fr_0.9fr]">
          {/* Brand panel */}
          <div className="relative hidden min-h-[580px] flex-col justify-between overflow-hidden bg-[#071F43] p-8 text-white md:flex">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(245,169,0,0.22),_transparent_38%),radial-gradient(circle_at_bottom_right,_rgba(255,255,255,0.12),_transparent_30%),linear-gradient(160deg,#071F43,#0E3160)]" />
            {!reduceMotion && (
              <motion.div
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent"
                initial={{ x: "-150%" }}
                animate={{ x: "450%" }}
                transition={{ duration: 6, repeat: Infinity, repeatDelay: 4, ease: "easeInOut" }}
              />
            )}

            <motion.div
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, delay: 0.1, ease: EASE }}
              className="relative z-10 flex items-center gap-4"
            >
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/20 bg-white/10 shadow-[0_12px_30px_rgba(0,0,0,0.25)]">
                <LogoMark className="h-9 w-9 text-[#F5A900]" />
              </div>
              <BrandWordmark tone="dark" size={22} />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2, ease: EASE }}
              className="relative z-10"
            >
              <p className="text-xs uppercase tracking-[0.35em] text-[#F5A900]/90">{t("login.tagline")}</p>
              <h1 className="mt-5 max-w-md text-4xl font-bold leading-tight text-white">{t("login.heroTitle")}</h1>
              <p className="mt-4 max-w-md text-base text-slate-300">{t("login.heroSubtitle")}</p>
            </motion.div>

            <motion.ul variants={stagger} initial="hidden" animate="show" className="relative z-10 grid gap-3">
              {FEATURES.map((key) => (
                <motion.li
                  key={key}
                  variants={rise}
                  whileHover={reduceMotion ? undefined : { x: 6 }}
                  className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-100 backdrop-blur-sm transition-colors hover:border-[#F5A900]/40 hover:bg-white/10"
                >
                  <span className="inline-flex h-2.5 w-2.5 shrink-0 rounded-full bg-[#F5A900] shadow-[0_0_16px_rgba(245,169,0,0.9)]" />
                  {t(key)}
                </motion.li>
              ))}
            </motion.ul>
          </div>

          {/* Form panel */}
          <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col bg-white/80 p-6 sm:p-8 md:p-10">
            <motion.div variants={rise} className="mb-8 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent text-primary-foreground shadow-[0_10px_30px_rgba(245,169,0,0.35)]">
                  <LogoMark className="h-7 w-7 text-white" />
                </div>
                <div>
                  <BrandWordmark tone="light" size={15} />
                  <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                    <Lock className="h-3 w-3" aria-hidden="true" />
                    {t("login.secureAccess")}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="sr-only">{t("login.language")}</span>
                <LanguageToggle language={language} onChange={setLanguage} layoutId="login-lang-toggle" />
              </div>
            </motion.div>

            <motion.div variants={rise} className="mb-6">
              <h2 className="text-[1.8rem] font-semibold leading-tight text-slate-900">{t("login.title")}</h2>
              <p className="mt-2 text-sm text-slate-500">{t("login.subtitle")}</p>
            </motion.div>

            <form className="space-y-4" onSubmit={handleSubmit}>
              <motion.div variants={rise} className="space-y-1.5">
                <Label htmlFor="email" className="text-sm font-medium text-slate-700">
                  {t("login.email")}
                </Label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                  <Input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="username"
                    autoFocus
                    required
                    placeholder={t("login.emailPlaceholder")}
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className={fieldClass}
                  />
                </div>
              </motion.div>

              <motion.div variants={rise} className="space-y-1.5">
                <Label htmlFor="password" className="text-sm font-medium text-slate-700">
                  {t("login.password")}
                </Label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-3.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                  <Input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className={`${fieldClass} pr-11`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((value) => !value)}
                    aria-label={showPassword ? t("login.hidePassword") : t("login.showPassword")}
                    aria-pressed={showPassword}
                    className="absolute right-2 top-1/2 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F5A900]/40"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </motion.div>

              {error && (
                <motion.p
                  role="alert"
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="animate-shake rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive"
                >
                  {error}
                </motion.p>
              )}

              <motion.div variants={rise} className="pt-1">
                <motion.div whileHover={{ scale: pending || reduceMotion ? 1 : 1.01 }} whileTap={{ scale: pending || reduceMotion ? 1 : 0.99 }}>
                  <Button
                    type="submit"
                    className="h-11 w-full rounded-xl bg-gradient-to-r from-primary to-[#1D4F8C] text-base text-white shadow-[0_12px_28px_rgba(18,59,109,0.35)] transition hover:from-[#0E3160] hover:to-primary hover:shadow-[0_16px_32px_rgba(18,59,109,0.45)] disabled:opacity-80"
                    disabled={pending}
                  >
                    {pending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                    {pending ? t("login.submitting") : t("login.submit")}
                  </Button>
                </motion.div>
              </motion.div>
            </form>

            <motion.p variants={rise} className="mt-auto pt-8 text-center text-xs text-slate-400">
              {t("login.footer")}
            </motion.p>
          </motion.div>
        </div>
      </motion.div>
    </div>
  );
}
