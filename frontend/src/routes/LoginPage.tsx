import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { ApiError } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import SecureIcon from "../assets/illustrations/auth/secure.svg?react";
import LogoMark from "../assets/animations/logo-mark.svg?react";

export function LoginPage() {
  const { login } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      setError(cause instanceof ApiError ? cause.message : "Unable to sign in");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="theme-login relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-8">
      <div className="absolute inset-0 overflow-hidden">
        <motion.div
          aria-hidden="true"
          className="absolute -left-16 top-16 h-72 w-72 rounded-full bg-primary/10 blur-3xl"
          animate={{ x: [0, 30, 0], y: [0, -20, 0], scale: [1, 1.1, 1] }}
          transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          aria-hidden="true"
          className="absolute -right-20 bottom-10 h-80 w-80 rounded-full bg-accent/10 blur-3xl"
          animate={{ x: [0, -25, 0], y: [0, 18, 0], scale: [1, 1.15, 1] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          aria-hidden="true"
          className="absolute left-1/2 top-1/2 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary/10"
          animate={{ rotate: 360 }}
          transition={{ duration: 28, repeat: Infinity, ease: "linear" }}
        />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45, ease: "easeOut" }}
        className="relative z-10 w-full max-w-5xl overflow-hidden rounded-[32px] border border-white/30 bg-white/75 shadow-[0_35px_90px_rgba(7,31,67,0.18)] backdrop-blur-xl"
      >
        <div className="grid md:grid-cols-[1.1fr_0.9fr]">
          <div className="relative hidden min-h-[560px] flex-col justify-between overflow-hidden bg-[#071F43] p-8 text-white md:flex">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(245,169,0,0.22),_transparent_38%),radial-gradient(circle_at_bottom_right,_rgba(255,255,255,0.12),_transparent_30%)]" />
            <motion.div
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="relative z-10 flex items-center gap-3"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/20 bg-white/10">
                <LogoMark className="h-8 w-8 text-[#F5A900]" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.35em] text-slate-300">Sonalim</p>
                <p className="text-lg font-semibold tracking-wide text-white">ERP</p>
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
              className="relative z-10"
            >
              <p className="text-xs uppercase tracking-[0.35em] text-primary/80">Production • Qualité • Performance</p>
              <h1 className="mt-5 max-w-md text-4xl font-bold leading-tight text-white">
                Manage your factory with confidence.
              </h1>
              <p className="mt-4 max-w-md text-base text-slate-300">
                Centralize production, quality, workforce, and stock visibility in one secure operational workspace.
              </p>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.28 }}
              className="relative z-10 grid gap-3"
            >
              {[
                "Production planning",
                "Quality and traceability",
                "Warehouse and performance tracking",
              ].map((item) => (
                <div key={item} className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-100 backdrop-blur-sm">
                  <span className="inline-flex h-2.5 w-2.5 rounded-full bg-[#F5A900] shadow-[0_0_16px_rgba(245,169,0,0.9)]" />
                  {item}
                </div>
              ))}
            </motion.div>
          </div>

          <div className="bg-white/80 p-6 sm:p-8 md:p-10">
            <motion.div
              initial={{ opacity: 0, x: 18 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.15 }}
              className="mb-6 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent text-base font-bold text-primary-foreground shadow-[0_10px_30px_rgba(245,169,0,0.35)]">
                  SE
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900">Sonalim ERP</p>
                  <p className="text-xs text-muted-foreground">Secure access</p>
                </div>
              </div>
            </motion.div>

            <Card className="border-0 bg-transparent shadow-none">
              <CardHeader className="px-0 pb-5">
                <CardTitle className="flex items-center gap-2 text-[1.8rem] leading-tight text-slate-900">
                  <SecureIcon className="h-5 w-5 text-primary" />
                  {t("login.title")}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <form className="space-y-4" onSubmit={handleSubmit}>
                  <div className="space-y-1.5">
                    <Label htmlFor="email" className="text-sm font-medium text-slate-700">{t("login.email")}</Label>
                    <Input
                      id="email"
                      name="email"
                      type="email"
                      autoComplete="username"
                      required
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      className="h-11 rounded-xl border-slate-200 bg-slate-50/80 text-slate-900 shadow-sm transition focus:border-primary focus:bg-white focus:ring-2 focus:ring-primary/15"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="password" className="text-sm font-medium text-slate-700">{t("login.password")}</Label>
                    <Input
                      id="password"
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      className="h-11 rounded-xl border-slate-200 bg-slate-50/80 text-slate-900 shadow-sm transition focus:border-primary focus:bg-white focus:ring-2 focus:ring-primary/15"
                    />
                  </div>
                  {error && <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
                  <motion.div whileHover={{ scale: pending ? 1 : 1.01 }} whileTap={{ scale: pending ? 1 : 0.99 }}>
                    <Button type="submit" className="h-11 w-full rounded-xl bg-gradient-to-r from-primary to-[#F7B500] text-white shadow-[0_12px_28px_rgba(245,169,0,0.35)] transition hover:shadow-[0_16px_32px_rgba(245,169,0,0.45)]" disabled={pending}>
                      {pending ? t("login.submitting") : t("login.submit")}
                    </Button>
                  </motion.div>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
