import { motion } from "framer-motion";
import type { Language } from "../../lib/i18n";
import { cn } from "../../lib/utils";

interface LanguageToggleProps {
  language: Language;
  onChange: (language: Language) => void;
  /** Distinct layoutId per instance so two toggles on screen never fight over the pill. */
  layoutId?: string;
  className?: string;
}

/** FR / EN pill switch. French is listed first: it is the working language of the plant. */
export function LanguageToggle({ language, onChange, layoutId = "lang-toggle", className }: LanguageToggleProps) {
  return (
    <div className={cn("relative flex shrink-0 rounded-md bg-muted p-0.5 text-[10px] font-semibold uppercase", className)}>
      {(["fr", "en"] as const).map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => onChange(code)}
          aria-pressed={language === code}
          className={cn(
            "relative z-10 rounded px-1.5 py-1 transition-colors",
            language === code ? "text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {language === code && (
            <motion.span
              layoutId={layoutId}
              className="absolute inset-0 -z-10 rounded bg-primary"
              transition={{ type: "spring", stiffness: 500, damping: 40 }}
            />
          )}
          {code}
        </button>
      ))}
    </div>
  );
}
