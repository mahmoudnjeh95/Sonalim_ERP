import { useLayoutEffect, useRef, useState, type FormEvent } from "react";
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
import { loginRevealed, stageStore, useStage } from "../components/patterns/brand3d/stageStore";
import logoMark from "../assets/icons/brand/logo-3d-mark-512.png";
import logoTile88 from "../assets/icons/brand/logo-3d-88.png";
import logoTile132 from "../assets/icons/brand/logo-3d-132.png";

const FEATURES: TranslationKey[] = ["login.feature.production", "login.feature.quality", "login.feature.warehouse"];

const EASE = [0.22, 1, 0.36, 1] as const;

/** The card: hidden while the welcome intro plays, then it rises; its children follow on their own delays. */
const card = {
  hidden: { opacity: 0, y: 18, scale: 0.98 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.5, ease: EASE } },
};
const fromLeft = {
  hidden: { opacity: 0, x: -16 },
  show: { opacity: 1, x: 0, transition: { duration: 0.5, delay: 0.1, ease: EASE } },
};
const fromBelow = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, delay: 0.2, ease: EASE } },
};
/** Entrance for the form column: each child arrives a beat after the previous one. */
const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.2 } },
};
const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

/**
 * Navy behind the brand panel's text, carried by the text's own wrapper: clear
 * at its top edge, at least 85 % from 32 px down (where the tagline starts), so
 * the text keeps its contrast whatever pasta passes behind and whatever the
 * panel's height (spec §3). The logo row above it stays clear for the live 3D logo.
 */
const PANEL_SCRIM = "linear-gradient(to bottom, rgba(7,31,67,0) 0px, rgba(7,31,67,0.85) 32px, rgba(7,31,67,0.9) 100%)";

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
  const panelSlotRef = useRef<HTMLDivElement>(null);
  const heroSlotRef = useRef<HTMLDivElement>(null);
  const revealed = useStage(loginRevealed);
  // The live 3D logo flies into the slots; until it draws (or with no live 3D) the baked mark holds the place.
  const live = useStage((s) => s.ready && !s.fallback);

  // Before paint, so the stage's navy is under the page from its first frame (no white flash).
  useLayoutEffect(() => {
    const slots = [panelSlotRef.current, heroSlotRef.current].filter((el): el is HTMLDivElement => el !== null);
    stageStore.set({ loginSlots: slots });
    return () => stageStore.set({ loginSlots: null });
  }, []);

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
    <div className="theme-login relative z-10 flex min-h-screen flex-col items-center justify-center overflow-hidden px-4 py-8">
      {/* Phones have no brand panel: the live logo hovers here, above the card. */}
      <div ref={heroSlotRef} aria-hidden="true" className="mb-6 h-24 w-24 md:hidden">
        {revealed && !live && <img src={logoMark} alt="" className="h-full w-full" />}
      </div>

      <motion.div
        variants={card}
        initial="hidden"
        animate={revealed ? "show" : "hidden"}
        className="relative w-full max-w-5xl overflow-hidden rounded-[32px] border border-white/15 shadow-[0_35px_90px_rgba(0,0,0,0.45)]"
      >
        <div className="grid grid-cols-1 md:grid-cols-[1.1fr_0.9fr]">
          {/* Brand panel: a window onto the 3D scene. */}
          <div className="relative hidden min-h-[580px] flex-col overflow-hidden border-r border-white/10 p-8 text-white md:flex">
            <motion.div variants={fromLeft} className="relative z-10 flex items-center gap-4">
              <div ref={panelSlotRef} aria-hidden="true" className="h-20 w-20 shrink-0">
                {!live && <img src={logoMark} alt="" className="h-full w-full" />}
              </div>
              <div className="rounded-xl bg-[#071F43]/85 px-3 py-2">
                <BrandWordmark tone="dark" size={22} />
              </div>
            </motion.div>

            <div
              className="relative z-10 -mx-8 -mb-8 mt-4 flex flex-1 flex-col justify-between gap-8 px-8 pb-8 pt-8"
              style={{ background: PANEL_SCRIM }}
            >
              <motion.div variants={fromBelow}>
                <p className="text-xs uppercase tracking-[0.35em] text-[#F5A900]/90">{t("login.tagline")}</p>
                <h1 className="mt-5 max-w-md text-4xl font-bold leading-tight text-white">{t("login.heroTitle")}</h1>
                <p className="mt-4 max-w-md text-base text-slate-300">{t("login.heroSubtitle")}</p>
              </motion.div>

              <motion.ul variants={stagger} className="grid gap-3">
                {FEATURES.map((key) => (
                  <motion.li
                    key={key}
                    variants={rise}
                    whileHover={reduceMotion ? undefined : { x: 6 }}
                    className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-100 transition-colors hover:border-[#F5A900]/40 hover:bg-white/10"
                  >
                    <span className="inline-flex h-2.5 w-2.5 shrink-0 rounded-full bg-[#F5A900] shadow-[0_0_16px_rgba(245,169,0,0.9)]" />
                    {t(key)}
                  </motion.li>
                ))}
              </motion.ul>
            </div>
          </div>

          {/* Form panel: opaque white (no blur over the live canvas, and no pasta ghosting through the fields). */}
          <motion.div variants={stagger} className="flex flex-col bg-white p-6 sm:p-8 md:p-10">
            <motion.div variants={rise} className="mb-8 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <img
                  src={logoTile88}
                  srcSet={`${logoTile88} 2x, ${logoTile132} 3x`}
                  alt=""
                  width={44}
                  height={44}
                  className="h-11 w-11 shrink-0 rounded-xl shadow-[0_10px_30px_rgba(245,169,0,0.35)]"
                />
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
